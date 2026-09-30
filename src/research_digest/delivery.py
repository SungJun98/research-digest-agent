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
            transport=self.transports.get(channel)
            if getattr(transport,'external',False):continue
            if not self.store.reserve_delivery(notification_id,channel):continue
            if notification.paper_ids and all(self.store.paper_delivered(p,channel) for p in notification.paper_ids):
                self.store.mark_delivered(notification_id,channel)
                continue
            success=False
            for attempt in range(3):
                try:
                    if transport is None:raise DeliveryError()
                    if hasattr(transport,'send_with_state'):
                        transport.send_with_state(self.store,notification_id,channel,notification.subject,notification.body)
                    else:transport.send(notification.subject,notification.body)
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


class ExternalTransport:
    """Stage an immutable outbox for a trusted connected-app sender to acknowledge."""
    external=True


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
    def send(self,subject,body):self._send(subject,body)
    def send_with_state(self,store,key,channel,subject,body):self._send(subject,body,store,key,channel)

    def _send(self,subject,body,store=None,key=None,channel=None):
        cfg=self.config
        units={recipient:hashlib.sha256(recipient.encode()).hexdigest() for recipient in cfg.recipients}
        remaining=[r for r in cfg.recipients if not store or not store.delivery_unit_done(key,channel,units[r])]
        if not remaining:return
        message=EmailMessage()
        try:
            message['Subject']=subject;message['From']=cfg.sender;message['To']=', '.join(cfg.recipients)
            if key:message['Message-ID']='<'+hashlib.sha256((key+channel).encode()).hexdigest()+'@research-digest.local>'
            message.set_content(body)
            context=ssl.create_default_context()
            if cfg.security=='ssl':server=smtplib.SMTP_SSL(cfg.host,cfg.port,timeout=30,context=context)
            else:server=smtplib.SMTP(cfg.host,cfg.port,timeout=30)
            with server:
                if cfg.security=='starttls':server.starttls(context=context)
                username=os.environ.get(cfg.username_env,'') if cfg.username_env else cfg.sender
                server.login(username,os.environ[cfg.password_env])
                for recipient in remaining:
                    refused=server.send_message(message,to_addrs=[recipient])
                    if refused:
                        codes=[details[0] for details in refused.values()]
                        raise DeliveryError('SMTP recipient refused',retryable=all(400<=code<500 for code in codes))
                    if store:store.mark_delivery_unit(key,channel,units[recipient])
        except DeliveryError:raise
        except (OSError,smtplib.SMTPException,ValueError,KeyError) as exc:
            codes=[details[0] for details in getattr(exc,'recipients',{}).values()]
            transient=isinstance(exc,OSError) or 400<=getattr(exc,'smtp_code',0)<500 or bool(codes and all(400<=c<500 for c in codes))
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
    def _parts(self,subject,body):
        text=f'{subject}\n\n{body}'
        return [{'text':text[start:start+35000]} for start in range(0,len(text),35000)]
    def send(self,subject,body):
        for payload in self._parts(subject,body):self._post(payload)
    def send_with_state(self,store,key,channel,subject,body):
        import json
        for index,payload in enumerate(self._parts(subject,body)):
            unit=str(index)+':'+hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
            if store.delivery_unit_done(key,channel,unit):continue
            self._post(payload)
            store.mark_delivery_unit(key,channel,unit)


class DiscordWebhookTransport(SlackWebhookTransport):
    def _parts(self,subject,body):
        text=f'{subject}\n\n{body}'
        return [{'content':text[start:start+1900],'allowed_mentions':{'parse':[]}} for start in range(0,len(text),1900)]
