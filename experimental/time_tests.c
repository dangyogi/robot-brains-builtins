// time_tests.c

#include <time.h>
#include <stdio.h>


int
main(int argc, char *argv[], char **env) {
    struct timespec my_timespec;
    double tv_sec, tv_hours;

    printf("sizeof(long) %ld\n", (long)sizeof(long));

    if (clock_getres(CLOCK_MONOTONIC, &my_timespec) == -1) {
        perror("clock_getres");
        return 1;
    }
    printf("res.tv_sec %ld\n", (long)my_timespec.tv_sec);
    printf("res.tv_nsec %ld\n", my_timespec.tv_nsec);

    if (clock_gettime(CLOCK_MONOTONIC, &my_timespec) == -1) {
        perror("clock_gettime");
        return 1;
    }
    tv_sec = (double)my_timespec.tv_sec;
    tv_hours = tv_sec / 3600.0;
    printf("time.tv_sec %g, hours %g, days %g\n",
           tv_sec, tv_hours, tv_hours / 24.0);
    printf("time.tv_nsec %ld\n", my_timespec.tv_nsec);

    return 0;
}
