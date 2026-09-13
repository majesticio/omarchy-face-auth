#define _GNU_SOURCE
#include <sudo_plugin.h>
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <json-c/json.h>
#include <systemd/sd-login.h>
#include <systemd/sd-bus.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/prctl.h>
#include <fcntl.h>
#include <errno.h>
#include <pwd.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

/* One DSO, loaded by sudo as audit + approval plugins and by its PAM stack.
 * Face evidence stays in this sudo process; no environment token, public IPC,
 * shared approval file, or cached authorization. The approval API supplies the
 * actual resolved command. Neither helper nor GUI executes that command. */
static bool audit_ready, face_matched;
static uid_t caller_uid, face_uid;
static pid_t owner_pid;
static struct timespec matched_at;
static char caller_tty[256], caller_cwd[4096];
static const char *module_path = "/usr/lib/security/pam_face_intent.so";

static const char *field(char *const values[], const char *key) {
    size_t n = strlen(key);
    if (values) for (size_t i = 0; values[i]; i++)
        if (!strncmp(values[i], key, n) && values[i][n] == '=') return values[i] + n + 1;
    return NULL;
}

static bool parse_uid(const char *s, uid_t *uid) {
    if (!s || !*s || strspn(s, "0123456789") != strlen(s)) return false;
    char *end; errno = 0;
    unsigned long n = strtoul(s, &end, 10);
    if (errno || *end || (unsigned long)(uid_t)n != n) return false;
    *uid = (uid_t)n;
    return true;
}

static bool approval_configured(void) {
    FILE *f = fopen("/etc/sudo.conf", "re");
    if (!f) return false;
    struct stat st;
    bool found = false;
    if (fstat(fileno(f), &st) == 0 && st.st_uid == 0 && !(st.st_mode & 022)) {
        char line[4096], directive[64], symbol[64], path[1024];
        while (fgets(line, sizeof(line), f)) {
            if (sscanf(line, "%63s %63s %1023s", directive, symbol, path) == 3 &&
                !strcmp(directive, "Plugin") && !strcmp(symbol, "face_approval") &&
                !strcmp(path, module_path)) found = true;
        }
    }
    fclose(f);
    return found;
}

static bool local_session(uid_t uid) {
    char *session = NULL, *type = NULL;
    bool ok = sd_uid_get_display(uid, &session) >= 0 && session &&
        sd_session_is_active(session) > 0 && sd_session_is_remote(session) == 0 &&
        sd_session_get_type(session, &type) >= 0 && !strcmp(type, "wayland");
    sd_bus *bus = NULL;
    char *path = NULL;
    int locked = 1;
    if (ok) ok = sd_bus_path_encode("/org/freedesktop/login1/session", session, &path) >= 0 &&
        sd_bus_open_system(&bus) >= 0 &&
        sd_bus_get_property_trivial(bus, "org.freedesktop.login1", path,
            "org.freedesktop.login1.Session", "LockedHint", NULL, 'b', &locked) >= 0 && !locked;
    sd_bus_unref(bus); free(path);
    free(session); free(type);
    return ok;
}

static int audit_open(unsigned int version, sudo_conv_t conv, sudo_printf_t print,
    char *const settings[], char *const user_info[], int optind,
    char *const argv[], char *const env[], char *const options[], const char **err) {
    (void)conv; (void)print; (void)settings; (void)optind; (void)argv;
    (void)env; (void)options; (void)err;
    face_matched = false; audit_ready = false; owner_pid = getpid();
    if (SUDO_API_VERSION_GET_MAJOR(version) != SUDO_API_VERSION_MAJOR) return -1;
    if (!parse_uid(field(user_info, "uid"), &caller_uid)) return 1;
    const char *tty = field(user_info, "tty"), *cwd = field(user_info, "cwd");
    snprintf(caller_tty, sizeof(caller_tty), "%s", tty ? tty : "No terminal");
    snprintf(caller_cwd, sizeof(caller_cwd), "%s", cwd ? cwd : "");
    audit_ready = approval_configured();
    return 1;
}

PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv) {
    (void)flags;
    if (argc != 1) return PAM_SERVICE_ERR;
    if (!strcmp(argv[0], "reset")) { face_matched = false; return PAM_IGNORE; }
    if (strcmp(argv[0], "mark")) return PAM_SERVICE_ERR;
    const void *service = NULL, *rhost = NULL;
    const char *user = NULL;
    if (!audit_ready || owner_pid != getpid() || !approval_configured()) return PAM_IGNORE;
    if (pam_get_item(pamh, PAM_SERVICE, &service) != PAM_SUCCESS || !service || strcmp(service, "sudo")) return PAM_IGNORE;
    if (pam_get_item(pamh, PAM_RHOST, &rhost) != PAM_SUCCESS || (rhost && *(const char *)rhost)) return PAM_IGNORE;
    if (pam_get_user(pamh, &user, NULL) != PAM_SUCCESS || !user) return PAM_IGNORE;
    struct passwd *pw = getpwnam(user);
    if (!pw || pw->pw_uid != caller_uid || !local_session(caller_uid)) return PAM_IGNORE;
    if (clock_gettime(CLOCK_MONOTONIC, &matched_at)) return PAM_SYSTEM_ERR;
    face_uid = pw->pw_uid; face_matched = true;
    return PAM_SUCCESS;
}
PAM_EXTERN int pam_sm_setcred(pam_handle_t *p, int f, int n, const char **a) {
    (void)p; (void)f; (void)n; (void)a; return PAM_SUCCESS;
}

static int approval_open(unsigned int v, sudo_conv_t c, sudo_printf_t p,
    char *const s[], char *const u[], int i, char *const a[], char *const e[],
    char *const o[], const char **err) {
    (void)c;(void)p;(void)s;(void)u;(void)i;(void)a;(void)e;(void)o;(void)err;
    return SUDO_API_VERSION_GET_MAJOR(v) == SUDO_API_VERSION_MAJOR ? 1 : -1;
}

static int run_dialog(json_object *payload) {
    const char *json = json_object_to_json_string_ext(payload, JSON_C_TO_STRING_PLAIN);
    size_t length = strlen(json);
    if (length > 65536) {
        json_object_object_add(payload, "password_only", json_object_new_boolean(true));
        json_object_object_add(payload, "command", json_object_new_string(""));
        json_object_object_add(payload, "argv", json_object_new_array());
        json_object_object_add(payload, "cwd", json_object_new_string(""));
        json_object_object_add(payload, "tty", json_object_new_string("Unavailable"));
        json = json_object_to_json_string_ext(payload, JSON_C_TO_STRING_PLAIN);
        length = strlen(json);
        if (length > 65536) return 0;
    }
    int pair[2];
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair)) return 0;
    pid_t request_pid = getpid();
    pid_t child = fork();
    if (child < 0) { close(pair[0]); close(pair[1]); return 0; }
    if (!child) {
        if (setresgid(0, 0, 0) || setresuid(0, 0, 0)) _exit(1);
        if (prctl(PR_SET_PDEATHSIG, SIGTERM) || getppid() != request_pid) _exit(1);
        if (dup2(pair[1], STDIN_FILENO) < 0) _exit(1);
        int nullfd = open("/dev/null", O_RDWR);
        if (nullfd < 0 || dup2(nullfd, STDOUT_FILENO) < 0 || dup2(nullfd, STDERR_FILENO) < 0) _exit(1);
        close_range(3, ~0U, 0);
        char *const clean_env[] = {"PATH=/usr/bin", "LANG=C.UTF-8", NULL};
        char *const args[] = {"/usr/bin/python3", "-I", "/usr/lib/omarchy-face-auth/backend.py", "approve", NULL};
        execve(args[0], args, clean_env); _exit(1);
    }
    close(pair[1]);
    struct timeval send_timeout = {.tv_sec = 3};
    setsockopt(pair[0], SOL_SOCKET, SO_SNDTIMEO, &send_timeout, sizeof(send_timeout));
    size_t sent = 0;
    while (sent < length) {
        ssize_t n = send(pair[0], json + sent, length - sent, MSG_NOSIGNAL);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        sent += (size_t)n;
    }
    shutdown(pair[0], SHUT_WR); close(pair[0]);
    /* The root backend enforces its own deadline. This independent watchdog
     * denies if it crashes, wedges, or outlives the original request. */
    int status = 0;
    for (int tick = 0; tick < 1250; tick++) {
        pid_t result = waitpid(child, &status, WNOHANG);
        if (result == child) return sent == length && WIFEXITED(status) && WEXITSTATUS(status) == 0;
        if (result < 0 && errno != EINTR) break;
        struct timespec pause = {.tv_nsec = 100000000}; nanosleep(&pause, NULL);
    }
    kill(child, SIGKILL); waitpid(child, &status, 0); return 0;
}

static int (*dialog_runner)(json_object *) = run_dialog;

static int approval_check(char *const info[], char *const argv[], char *const env[], const char **err) {
    (void)env;
    if (!face_matched) return 1; /* Normal password/NOPASSWD policy is unchanged. */
    face_matched = false; /* Consume exactly once, including every failure path. */
    if (err) *err = "Face authorization was not approved; command cancelled.";
    if (!audit_ready || owner_pid != getpid() || face_uid != caller_uid || !local_session(caller_uid)) return 0;
    uid_t runas = 0;
    const char *command = field(info, "command");
    bool password_only = !parse_uid(field(info, "runas_uid"), &runas) ||
        !command || command[0] != '/' || !argv || !argv[0];
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return 0;
    double age = now.tv_sec - matched_at.tv_sec + (now.tv_nsec - matched_at.tv_nsec) / 1e9;
    json_object *payload = json_object_new_object(), *args = json_object_new_array();
    if (!payload || !args) { if(payload) json_object_put(payload); if(args) json_object_put(args); return 0; }
    size_t bytes = 0;
    for (size_t i = 0; !password_only && argv[i]; i++) {
        size_t arg_length = strlen(argv[i]);
        if (i >= 256 || arg_length > 8000 - bytes) { password_only = true; break; }
        bytes += arg_length;
        json_object_array_add(args, json_object_new_string(argv[i]));
    }
    if (password_only) { json_object_put(args); args = json_object_new_array(); }
    json_object_object_add(payload, "argv", args);
    json_object_object_add(payload, "command", json_object_new_string(password_only ? "" : command));
    json_object_object_add(payload, "password_only", json_object_new_boolean(password_only));
    json_object_object_add(payload, "uid", json_object_new_int64(caller_uid));
    json_object_object_add(payload, "runas_uid", json_object_new_int64(runas));
    json_object_object_add(payload, "tty", json_object_new_string(caller_tty));
    json_object_object_add(payload, "cwd", json_object_new_string(caller_cwd));
    json_object_object_add(payload, "remaining", json_object_new_double(age >= 0 && age < 30 ? 30 - age : 0));
    json_object_object_add(payload, "expires_at", json_object_new_double(matched_at.tv_sec + matched_at.tv_nsec / 1e9 + 30));
    int accepted = dialog_runner(payload); json_object_put(payload);
    if (accepted && err) *err = NULL;
    return accepted;
}

static void approval_close(void) { face_matched = false; }
static void audit_close(int t, int s) { (void)t;(void)s; audit_ready = face_matched = false; }
__attribute__((visibility("default"))) struct audit_plugin face_audit = {
    .type=SUDO_AUDIT_PLUGIN, .version=SUDO_API_VERSION, .open=audit_open, .close=audit_close
};
__attribute__((visibility("default"))) struct approval_plugin face_approval = {
    .type=SUDO_APPROVAL_PLUGIN, .version=SUDO_API_VERSION, .open=approval_open,
    .close=approval_close, .check=approval_check
};
