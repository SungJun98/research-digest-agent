from datetime import datetime,date,time
from zoneinfo import ZoneInfo
import time as wall_time


def due_digest(now:datetime,timezone_name:str,digest_at:time,last_success_day:date|None):
    local=now.astimezone(ZoneInfo(timezone_name))
    today=local.date()
    if local.time().replace(tzinfo=None)<digest_at or (last_success_day and last_success_day>=today):return None
    return today


def serve(runner_factory,sleep=wall_time.sleep):
    """Reload config every minute; each runner uses a cross-process state lock."""
    while True:
        runner=runner_factory()
        reports=runner.tick(runner.clock())
        for report in reports:
            if report.source_failures or (report.delivery and report.delivery.failed):
                print('research-digest: incomplete run; inspect preview/doctor and channel configuration',flush=True)
        sleep(60)
