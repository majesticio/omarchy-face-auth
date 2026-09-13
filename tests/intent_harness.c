/* Isolated fixtures replace OS/session/GUI boundaries. Never install this. */
#define fopen fixture_fopen
#define fstat fixture_fstat
#define sd_uid_get_display fixture_display
#define sd_session_is_active fixture_active
#define sd_session_is_remote fixture_remote
#define sd_session_get_type fixture_type
#define sd_bus_open_system fixture_bus_open
#define sd_bus_get_property_trivial fixture_bus_property
#define sd_bus_unref fixture_bus_unref
#define setresuid fixture_setresuid
#define setresgid fixture_setresgid
#include "../native/intent.c"
#undef fopen
#undef fstat
#undef setresuid
#undef setresgid
#include <assert.h>
#include <sys/mman.h>
#include <security/pam_appl.h>
extern int fstat(int, struct stat *);

static bool configured = true, trusted = true, session_active = true;
static int gui_exit;
static const char *expected_command;
FILE *fixture_fopen(const char *path, const char *mode) {
    (void)mode;
    assert(!strcmp(path, "/etc/sudo.conf"));
    int fd = memfd_create("sudo-conf-fixture", MFD_CLOEXEC);
    assert(fd >= 0);
    if (configured) {
        const char line[] = "Plugin face_approval /usr/lib/security/pam_face_intent.so\n";
        assert(write(fd, line, sizeof(line) - 1) == (ssize_t)(sizeof(line) - 1));
    }
    assert(lseek(fd, 0, SEEK_SET) == 0);
    FILE *file = fdopen(fd, "r");
    assert(file);
    return file;
}
int fixture_fstat(int fd, struct stat *st) {
    int ret = fstat(fd, st);
    st->st_uid = trusted ? 0 : 1000;
    st->st_mode = S_IFREG | 0600;
    return ret;
}
int fixture_display(uid_t u, char **s) { (void)u; *s = strdup("fixture-session"); return 0; }
int fixture_active(const char *s) { (void)s; return session_active; }
int fixture_remote(const char *s) { (void)s; return 0; }
int fixture_type(const char *s, char **t) { (void)s; *t = strdup("wayland"); return 0; }
int fixture_bus_open(sd_bus **bus) { *bus = NULL; return 0; }
sd_bus *fixture_bus_unref(sd_bus *bus) { (void)bus; return NULL; }
int fixture_bus_property(sd_bus *bus, const char *destination, const char *path, const char *interface,
                         const char *member, sd_bus_error *error, char type, void *ptr) {
    (void)bus;(void)destination;(void)path;(void)interface;(void)member;(void)error;(void)type;
    *(int *)ptr = 0; return 0;
}
int fixture_setresuid(uid_t a, uid_t b, uid_t c) { (void)a;(void)b;(void)c; return 0; }
int fixture_setresgid(gid_t a, gid_t b, gid_t c) { (void)a;(void)b;(void)c; return 0; }
static int fixture_dialog(json_object *payload) {
    json_object *command = NULL, *argv = NULL;
    assert(json_object_object_get_ex(payload, "command", &command));
    assert(!strcmp(json_object_get_string(command), expected_command));
    assert(json_object_object_get_ex(payload, "argv", &argv));
    assert(json_object_array_length(argv) == 3);
    return gui_exit == 0;
}
static int conversation(int n, const struct pam_message **m, struct pam_response **r, void *d) {
    (void)n;(void)m;(void)r;(void)d; return PAM_CONV_ERR;
}
int main(void) {
    dialog_runner = fixture_dialog;
    struct passwd *pw = getpwuid(getuid()); assert(pw);
    struct pam_conv conv = {conversation, NULL}; pam_handle_t *pamh = NULL;
    assert(pam_start("sudo", pw->pw_name, &conv, &pamh) == PAM_SUCCESS);
    const char *mark[] = {"mark"}, *reset[] = {"reset"};
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    char uid_string[64]; snprintf(uid_string, sizeof(uid_string), "uid=%u", getuid());
    char *user_info[] = {uid_string, "tty=/dev/pts/test", "cwd=/tmp", NULL};
    audit_open(SUDO_API_VERSION, NULL, NULL, NULL, user_info, 0, NULL, NULL, NULL, NULL);
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_SUCCESS && face_matched);
    assert(pam_sm_authenticate(pamh, 0, 1, reset) == PAM_IGNORE && !face_matched);
    configured = false;
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    configured = true; trusted = false;
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    trusted = true; session_active = false;
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    session_active = true;
    pam_set_item(pamh, PAM_RHOST, "remote.example");
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    pam_set_item(pamh, PAM_RHOST, "");
    char *info[] = {"command=/usr/bin/printf", "runas_uid=0", NULL};
    char *args[] = {"printf", "%s", "one argument; with spaces", NULL};
    expected_command = "/usr/bin/printf";
    const char *err = NULL;
    assert(approval_check(info, args, NULL, &err) == 1); /* password/NOPASSWD */
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_SUCCESS);
    gui_exit = 0;
    assert(approval_check(info, args, NULL, &err) == 1 && !face_matched);
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_SUCCESS);
    gui_exit = 1;
    assert(approval_check(info, args, NULL, &err) == 0 && !face_matched);
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_SUCCESS);
    owner_pid++;
    assert(approval_check(info, args, NULL, &err) == 0 && !face_matched);
    owner_pid = getpid();
    audit_close(0, 0);
    assert(pam_sm_authenticate(pamh, 0, 1, mark) == PAM_IGNORE);
    pam_end(pamh, PAM_SUCCESS);
    puts("Intent harness passed: missing plugins, trust, remote/session gating, exact argv, approve/deny, process binding.");
    return 0;
}
