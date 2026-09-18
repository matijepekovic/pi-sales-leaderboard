"""Exit-status contract between isolated Gallery processing and its worker."""

# sysexits.h EX_TEMPFAIL semantics: processing can be retried with the same source
# and durable completed-page checkpoint.
RETRYABLE_EXIT = 75
