"""Bounded public-source adapters. Exceptions never include response bodies or credentials."""
from __future__ import annotations

import time
from threading import Lock
import httpx


class SourceError(RuntimeError):
    pass


class RateLimiter:
    def __init__(self, interval=0.0, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last = None
        self.lock = Lock()

    def request(self, client, method, url, **kwargs):
        # Hold the lock through the response: arXiv allows one connection at a time.
        with self.lock:
            if self.last is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last)))
            self.last = self.clock()
            return client.request(method, url, **kwargs)


ARXIV_LIMITER = RateLimiter(3.0)


def request_json(client, url, *, label, params=None, headers=None, limiter=None, sleep=time.sleep):
    response = request(client, url, label=label, params=params, headers=headers, limiter=limiter, sleep=sleep)
    try:
        return response.json()
    except (ValueError, TypeError):
        raise SourceError(f'{label}: invalid response') from None


def request(client, url, *, label, params=None, headers=None, limiter=None, sleep=time.sleep):
    for attempt in range(3):
        try:
            response = (limiter or RateLimiter()).request(client, 'GET', url, params=params, headers=headers, timeout=30, follow_redirects=False)
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < 2:
                    retry = response.headers.get('Retry-After', '')
                    sleep(min(60, float(retry)) if retry.isdigit() else 2 ** attempt)
                    continue
            response.raise_for_status()
            return response
        except httpx.HTTPError:
            if attempt == 2:
                break
            if 'response' in locals() and response.status_code < 500 and response.status_code != 429:
                break
            sleep(2 ** attempt)
    raise SourceError(f'{label}: request failed') from None
