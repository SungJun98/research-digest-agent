"""Per-channel durable outbox. Network failures are reported without secret strings."""
from __future__ import annotations
from dataclasses import dataclass,field
import hashlib
import os
from pathlib import Path
import smtplib
import ssl
import tempfile
import time
from email.message import EmailMessage
import httpx
from .render import safe_url


class DeliveryError(RuntimeError):
    def __init__(self,safe_message='delivery failed',retryable=False):
        super().__init__(safe_message)
        self.retryable=retryable


@dataclass
class DeliveryReport:
    delivered: list[str] = field(default_factory=list)
    failed: dict[str,str] = field(default_factory=dict)


class Dispatcher:
    def __init__(self,store,transports,sleep=time.sleep):
        self.store,self.transports,self.sleep=store,transports,sleep

    def send(self,notification_id,subject,body,channels):
        self.store.create_notification(notification_id,subject,body,channels)
        notification=next((n for n in self.store.pending_notifications() if n.id==notification_id),None)
        report=DeliveryReport()
        if not notification:return report
        for channel in notification.pending_channels:
            if not self.store.reserve_delivery(notification_id,channel):continue
            transport=self.transports.get(channel)
            success=False
            for attempt in range(3):
                try:
                    if transport is None:raise DeliveryError()
                    transport.send(notification.subject,notification.body)
                    success=True
                    break
                except DeliveryError as exc:
                    if exc.retryable and attempt<2:self.sleep(2**attempt)
                    else:break
                except Exception:
                    break
            if success:
                self.store.mark_delivered(notification_id,channel)
                report.delivered.append(channel)
            else:
                self.store.mark_failed(notification_id,channel)
                report.failed[channel]=f'{channel}: delivery failed; pending retry'
        return report


class MarkdownTransport:
    def __init__(self,directory):self.directory=Path(directory).expanduser()
    def send(self,subject,body):
        self.directory.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256((subject+'\n'+body).encode()).hexdigest()[:20]
        filename=self.directory/f'{digest}.md'
        temporary=None
        try:
            with tempfile.NamedTemporaryFile('w',dir=self.directory,encoding='utf-8',delete=False) as handle:
                temporary=handle.name
                handle.write(f'# {subject}\n\n{body.rstrip()}\n')
            os.replace(temporary,filename)
        finally:
            if temporary and os.path.exists(temporary):os.unlink(temporary)


class SmtpTransport:
    def __init__(self,config):self.config=config
    def send(self,subject,body):
        cfg=self.config
        message=EmailMessage()
        try:
            message['Subject']=subject;message['From']=cfg.sender;message['To']=', '.join(cfg.recipients)
            message.set_content(body)
            context=ssl.create_default_context()
            if cfg.security=='ssl':server=smtplib.SMTP_SSL(cfg.host,cfg.port,timeout=30,context=context)
            else:server=smtplib.SMTP(cfg.host,cfg.port,timeout=30)
            with server:
                if cfg.security=='starttls':server.starttls(context=context)
                username=os.environ.get(cfg.username_env,'') if cfg.username_env else cfg.sender
                server.login(username,os.environ[cfg.password_env])
                refused=server.send_message(message)
                if refused:raise DeliveryError('SMTP recipients refused')
        except DeliveryError:raise
        except (OSError,smtplib.SMTPException,ValueError,KeyError) as exc:
            transient=isinstance(exc,OSError) or 400<=getattr(exc,'smtp_code',0)<500
            raise DeliveryError('SMTP delivery failed',retryable=transient) from None


class SlackWebhookTransport:
    def __init__(self,client,url):self.client,self.url=client,url
    def _post(self,payload):
        if not safe_url(self.url):raise DeliveryError('invalid webhook URL')
        try:
            response=self.client.post(self.url,json=payload,timeout=30,follow_redirects=False)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            status=getattr(getattr(exc,'response',None),'status_code',0)
            raise DeliveryError('webhook unavailable',retryable=status==429 or status>=500 or not status) from None
    def send(self,subject,body):
        text=f'{subject}\n\n{body}'
        for start in range(0,len(text),35000):self._post({'text':text[start:start+35000]})


class DiscordWebhookTransport(SlackWebhookTransport):
    def send(self,subject,body):
        text=f'{subject}\n\n{body}'
        for start in range(0,len(text),1900):self._post({'content':text[start:start+1900],'allowed_mentions':{'parse':[]}})
