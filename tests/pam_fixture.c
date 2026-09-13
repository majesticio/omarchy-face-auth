#define _POSIX_C_SOURCE 200809L
#include <security/pam_modules.h>
#include <security/pam_ext.h>
#include <stdlib.h>
#include <string.h>

/* TEST ONLY: substitutes a camera/password outcome in a private PAM directory.
 * Never install this file or its compiled module. */
PAM_EXTERN int pam_sm_authenticate(pam_handle_t *pamh, int flags,
                                  int argc, const char **argv) {
    (void)flags;
    if (argc != 1) return PAM_SERVICE_ERR;
    if (!strcmp(argv[0], "recognize")) {
        pam_info(pamh, "fixture:face-match");
        return PAM_SUCCESS;
    }
    if (!strcmp(argv[0], "reject")) {
        pam_info(pamh, "fixture:face-rejected");
        return PAM_AUTH_ERR;
    }
    if (!strcmp(argv[0], "ignore")) return PAM_IGNORE;
    if (!strcmp(argv[0], "password")) {
        char *answer = NULL;
        int result = pam_prompt(pamh, PAM_PROMPT_ECHO_OFF, &answer, "Fixture password: ");
        int ok = result == PAM_SUCCESS && answer && !strcmp(answer, "correct-password");
        free(answer);
        return ok ? PAM_SUCCESS : PAM_AUTH_ERR;
    }
    return PAM_SERVICE_ERR;
}

PAM_EXTERN int pam_sm_setcred(pam_handle_t *pamh, int flags,
                              int argc, const char **argv) {
    (void)pamh;
    (void)flags;
    (void)argc;
    (void)argv;
    return PAM_SUCCESS;
}
