#define _POSIX_C_SOURCE 200809L
#include <security/pam_appl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <pwd.h>
#include <unistd.h>

struct answers { const char *confirmation, *password; double delay; };
static int converse(int count, const struct pam_message **messages,
                    struct pam_response **responses, void *context) {
    struct answers *answers = context;
    *responses = calloc((size_t)count, sizeof(**responses));
    if (!*responses) return PAM_BUF_ERR;
    for (int i = 0; i < count; i++) {
        printf("message:%s\n", messages[i]->msg);
        const char *answer = NULL;
        if (messages[i]->msg_style == PAM_PROMPT_ECHO_ON) {
            if (answers->delay > 0) {
                struct timespec t = {(time_t)answers->delay,
                    (long)((answers->delay - (time_t)answers->delay) * 1e9)};
                nanosleep(&t, NULL);
            }
            answer = answers->confirmation;
        } else if (messages[i]->msg_style == PAM_PROMPT_ECHO_OFF) {
            answer = answers->password;
        }
        if (answer) (*responses)[i].resp = strdup(answer);
    }
    return PAM_SUCCESS;
}

int main(int argc, char **argv) {
    if (argc != 7) return 2;
    struct answers answers = {argv[3], argv[4], atof(argv[6])};
    struct pam_conv conv = {converse, &answers};
    pam_handle_t *pamh = NULL;
    struct passwd *user = getpwuid(getuid());
    if (!user) return 2;
    int result = pam_start_confdir(argv[2], user->pw_name, &conv, argv[1], &pamh);
    if (result == PAM_SUCCESS && *argv[5]) result = pam_set_item(pamh, PAM_RHOST, argv[5]);
    if (result == PAM_SUCCESS) result = pam_authenticate(pamh, 0);
    printf("result:%d\n", result);
    if (pamh) pam_end(pamh, result);
    return result == PAM_SUCCESS ? 0 : 1;
}
