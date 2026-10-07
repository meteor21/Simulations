from __future__ import annotations
import email.utils
import ipaddress
import socket
import time
from datetime import datetime,timezone
from urllib.parse import urlsplit
import requests
from urllib3.util.retry import Retry

class BudgetExceeded(RuntimeError): pass
class AccessBlocked(RuntimeError): pass

class HttpClient:
    """Bounded, sequential HTTP. API-level pacing is intentional; no parallel quota evasion."""
    def __init__(self,max_requests=100,timeout=30,interval=1.1,session=None,before_request=None):
        if type(max_requests) is not int or max_requests<1: raise ValueError('max_requests must be a positive integer')
        self.max_requests=max_requests; self.timeout=timeout; self.interval=interval
        self.before_request=before_request
        self.requests_used=0; self.session=session or requests.Session(); self.last={}
        self.session.headers.update({'User-Agent':'CandidateStandingResearch/0.1'})
        # All retries belong to this counted loop, including caller-supplied sessions.
        for adapter in getattr(self.session,'adapters',{}).values():
            adapter.max_retries=Retry(total=0,connect=0,read=0,redirect=0,status=0)

    def get(self,url,*,params=None,headers=None,min_interval=None,max_bytes=10_000_000):
        domain=urlsplit(url).netloc
        for attempt in range(3):
            if self.requests_used>=self.max_requests: raise BudgetExceeded('HTTP request budget exhausted; resume later.')
            pause=max(0,(min_interval if min_interval is not None else self.interval)-(time.monotonic()-self.last.get(domain,0)))
            if pause: time.sleep(pause)
            # A persistent pilot ledger can reserve a request before it is sent.
            # Reservations remain consumed if the process exits during the request.
            if self.before_request is not None: self.before_request()
            self.requests_used+=1; self.last[domain]=time.monotonic()
            try:
                r=self.session.get(url,params=params,headers=headers,timeout=self.timeout,
                                   allow_redirects=False,stream=True,verify=True)
                if r.status_code in (429,500,502,503,504):
                    raw=r.headers.get('Retry-After','')
                    delay=2**(attempt+1)
                    try: delay=max(delay,float(raw))
                    except ValueError:
                        try: delay=max(delay,(email.utils.parsedate_to_datetime(raw)-datetime.now(timezone.utc)).total_seconds())
                        except (TypeError,ValueError): pass
                    r.close()
                    if delay>120 or attempt==2: raise AccessBlocked('Server requested a pause or remained unavailable; job is resumable.')
                    time.sleep(delay); continue
                if r.status_code in (401,403):
                    r.close(); raise AccessBlocked(f'Access denied ({r.status_code}) for {domain}; no bypass attempted.')
                # Return redirects to caller; article redirects require another allowlist check.
                if 300<=r.status_code<400:
                    r._content=b''; r.close(); return r
                if r.status_code==404:
                    r._content=b''; r.close(); return r
                if r.status_code >= 400:
                    code=r.status_code; r.close(); raise AccessBlocked(f'HTTP {code} from {domain}.')
                body=bytearray()
                for chunk in r.iter_content(65536):
                    body.extend(chunk)
                    if len(body)>max_bytes:
                        r.close(); raise AccessBlocked('Response exceeded configured byte limit.')
                r._content=bytes(body); r._content_consumed=True; r.close(); return r
            except (requests.Timeout,requests.ConnectionError) as e:
                if attempt==2: raise AccessBlocked(f'Network failure at {domain}: {type(e).__name__}') from e
                time.sleep(2**attempt)
        raise AccessBlocked('Retry budget exhausted.')


def require_public_url(url):
    p=urlsplit(url)
    if p.scheme not in {'https','http'} or not p.hostname or p.username or p.password:
        raise AccessBlocked('Invalid public article URL.')
    if p.port not in (None,80,443): raise AccessBlocked('Nonstandard port blocked.')
    try: addresses=socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)
    except OSError as e: raise AccessBlocked('Cannot resolve article hostname.') from e
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise AccessBlocked('Private, loopback, reserved, or local network address blocked.')
