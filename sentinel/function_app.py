import logging

import azure.functions as func

app = func.FunctionApp()


@app.timer_trigger(
    schedule="%POLL_SCHEDULE%",
    arg_name="timer",
    run_on_startup=False,
    use_monitor=True,
)
def poll_audit_events(timer: func.TimerRequest) -> None:
    # Imported lazily so a configuration error surfaces as a clear function
    # failure in Application Insights instead of a host load error.
    from innerlogic_sentinel.runner import run

    if timer.past_due:
        logging.warning("Timer is past due; running now")
    # Exceptions propagate on purpose: the run is marked failed and the next
    # tick retries from the last committed checkpoint.
    run()
