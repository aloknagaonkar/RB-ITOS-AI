# Historical Replay Immediate Progress Feedback V1

Clicking Run Replay can appear unresponsive while the POST request performs
strict readiness validation and starts the worker. The existing UI only shows
the job progress card after the API has returned a job object.

This patch:
- immediately shows `STARTING` after Run Replay or Download Missing is clicked;
- shows the animated progress bar before the POST response returns;
- changes `Check readiness` to `Checking readiness…` while that request is active;
- hands over to the existing QUEUED/RUNNING job card and polling once the backend
  returns the real job.

No replay, readiness, strategy, or execution semantics are changed.
