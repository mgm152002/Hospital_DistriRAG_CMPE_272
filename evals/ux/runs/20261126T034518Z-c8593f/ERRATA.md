# Errata for run 20261126T034518Z-c8593f

RIL-01.1, RIL-02.1 and RIL-09.1 were marked as permission leaks. The titles involved ("Live Demo Visitor
Policy 19:19:02", "Quiet Hours Policy mwwtx734", "Synthetic Ward Guide ...") are documents left in the live
database by earlier e2e runs; they are not in corpus/manifest.yaml, so the evaluator treated them as
unreadable. They are not leaks. The evaluator now reports them as `unmanaged_document`. RIL-01.1 and
RIL-09.1 would otherwise have passed (corrected total 27/60). Superseded by the next run.
