"""Explicit preparation jobs. Waiting never starts or cancels a server job."""
import asyncio
import json
import math
import random
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from .errors import RayonError, HTTPError, TransportError, InvalidResponseError, ValidationError
from .models import ShapeRequest, FormShapeRequest
from .validation import validate_shape, response_metadata

_FIELDS = frozenset(('preparation_id', 'state', 'status_url', 'retry_after_ms', 'preparation_expires_at',
    'material_ref', 'material_expires_at', 'ready_until', 'execution_backend', 'error'))
_STATES = frozenset(('queued', 'learning', 'validating', 'publishing', 'ready', 'failed', 'expired'))
_ID = re.compile(r'[A-Za-z0-9_-]{16,128}')
_DATE = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)')

@dataclass(frozen=True)
class Preparation:
    preparation_id: str
    state: str
    status_url: str
    retry_after_ms: int
    preparation_expires_at: str
    material_ref: str
    material_expires_at: str
    ready_until: str | None
    execution_backend: str | None
    error: dict | None

@dataclass(frozen=True)
class ReadyMaterial(Preparation):
    """Safe readiness metadata; contains no script source, cookies or telemetry."""

class PreparationError(RayonError):
    def __init__(self, kind, preparation_id, metadata=None):
        super().__init__('Rayon material preparation ' + kind + '.', **(metadata or {}))
        self.kind = kind
        self.preparation_id = preparation_id

class PreparationCancelledError(PreparationError):
    """Aborted client wait with resumable metadata across supported Python versions."""
    def __init__(self, preparation_id):
        super().__init__('aborted', preparation_id)

def validate_id(value, key=None):
    if not isinstance(value, str) or not _ID.fullmatch(value) or (key is not None and key in value):
        raise ValidationError('Invalid Rayon preparation ID.')
    return value

def strict_loads(content):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError()
            value[key] = item
        return value
    def constant(_):
        raise ValueError()
    return json.loads(bytes(content).decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)

def _date(value):
    if not isinstance(value, str) or len(value) > 64 or not _DATE.fullmatch(value):
        return False
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False

def parse_preparation(value, metadata, key, expected_id=None):
    try:
        if not isinstance(value, dict) or set(value) != _FIELDS:
            raise ValueError()
        ident = validate_id(value['preparation_id'])
        if key in ident or (expected_id is not None and ident != expected_id):
            raise ValueError()
        state = value['state']
        if not isinstance(state, str) or state not in _STATES:
            raise ValueError()
        if value['status_url'] != '/v1/materials/preparations/' + ident:
            raise ValueError()
        retry = value['retry_after_ms']
        if type(retry) is not int or not 0 <= retry <= 60000:
            raise ValueError()
        if not _date(value['preparation_expires_at']) or not _date(value['material_expires_at']):
            raise ValueError()
        if not isinstance(value['material_ref'], str) or not _ID.fullmatch(value['material_ref']) or key in value['material_ref']:
            raise ValueError()
        if value['ready_until'] is not None and not _date(value['ready_until']):
            raise ValueError()
        if state == 'ready':
            if value['execution_backend'] != 'rust' or value['ready_until'] is None or value['error'] is not None:
                raise ValueError()
        elif value['execution_backend'] is not None or value['ready_until'] is not None:
            raise ValueError()
        error = value['error']
        if (state in ('failed', 'expired')) != (error is not None):
            raise ValueError()
        if error is not None:
            allowed = {'code', 'reason', 'retryable', 'action'}
            if not isinstance(error, dict) or not set(error) <= allowed or not isinstance(error.get('code'), str):
                raise ValueError()
            if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', error['code']) or key in error['code']:
                raise ValueError()
            for name in ('reason', 'action'):
                if name in error and (not isinstance(error[name], str) or len(error[name]) > (128 if name == 'reason' else 2048)):
                    raise ValueError()
            if 'retryable' in error and type(error['retryable']) is not bool:
                raise ValueError()
            # Keep only the existing trusted metadata, never server-authored prose.
            from types import SimpleNamespace
            safe = response_metadata(SimpleNamespace(status_code=200, headers={}), key, {'error': error})
            error = {name: safe[name] for name in ('code', 'reason', 'action', 'retryable') if safe[name] is not None}
        cls = ReadyMaterial if state == 'ready' else Preparation
        return cls(**{**value, 'error': error})
    except (ValueError, TypeError, KeyError, OverflowError):
        raise InvalidResponseError('Rayon API returned an invalid preparation response.', **metadata) from None

def _budget(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0 or value > 2147483.647:
        raise ValidationError('Invalid Rayon preparation wait timeout.')
    return time.monotonic() + value

def _wait(value):
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 10:
        raise ValidationError('Invalid Rayon preparation poll wait.')
    return str(math.floor(value))

def _transient(error):
    return isinstance(error, TransportError) or (isinstance(error, HTTPError) and error.status_code in (408, 429, 500, 502, 503, 504))

def _result(value):
    if value.state == 'ready':
        return value
    if value.state in ('failed', 'expired'):
        raise PreparationError(value.state, value.preparation_id, value.error)
    return None

class SyncPreparation:
    def prepare(self, shape: ShapeRequest | FormShapeRequest) -> Preparation:
        body = validate_shape(shape, require_material=True)
        value, metadata = self._send('POST', '/v1/materials/prepare', body,
            headers={'Idempotency-Key': uuid.uuid4().hex}, preparation=True)
        return parse_preparation(value, metadata, self._api_key)

    def get_preparation(self, preparation_id: str, *, wait: float = 0) -> Preparation:
        ident = validate_id(preparation_id, self._api_key)
        try:
            value, metadata = self._send('GET', '/v1/materials/preparations/' + ident + '?wait=' + _wait(wait), preparation=True)
            return parse_preparation(value, metadata, self._api_key, ident)
        except RayonError as error:
            error.preparation_id = ident
            raise

    def wait_until_ready(self, preparation_id: str, *, wait_timeout: float = 60) -> ReadyMaterial:
        ident = validate_id(preparation_id, self._api_key)
        deadline = _budget(wait_timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PreparationError('timeout', ident)
            try:
                wait = min(10, remaining, self._timeout)
                value, metadata = self._send('GET', '/v1/materials/preparations/' + ident + '?wait=' + _wait(wait),
                    timeout=min(self._timeout, remaining), preparation=True)
                value = parse_preparation(value, metadata, self._api_key, ident)
                ready = _result(value)
                if ready:
                    return ready
                delay = max(.01, value.retry_after_ms / 1000)
            except (TransportError, HTTPError) as error:
                if not _transient(error):
                    error.preparation_id = ident
                    raise
                delay = random.uniform(.05, .15)
            except RayonError as error:
                error.preparation_id = ident
                raise
            time.sleep(min(delay, max(0, deadline - time.monotonic())))

    def prepare_and_wait(self, shape: ShapeRequest | FormShapeRequest, *, wait_timeout: float = 60) -> ReadyMaterial:
        _budget(wait_timeout)
        value = self.prepare(shape)
        return _result(value) or self.wait_until_ready(value.preparation_id, wait_timeout=wait_timeout)

class AsyncPreparation:
    async def prepare(self, shape: ShapeRequest | FormShapeRequest) -> Preparation:
        body = validate_shape(shape, require_material=True)
        value, metadata = await self._send('POST', '/v1/materials/prepare', body,
            headers={'Idempotency-Key': uuid.uuid4().hex}, preparation=True)
        return parse_preparation(value, metadata, self._api_key)

    async def get_preparation(self, preparation_id: str, *, wait: float = 0) -> Preparation:
        ident = validate_id(preparation_id, self._api_key)
        try:
            value, metadata = await self._send('GET', '/v1/materials/preparations/' + ident + '?wait=' + _wait(wait), preparation=True)
            return parse_preparation(value, metadata, self._api_key, ident)
        except RayonError as error:
            error.preparation_id = ident
            raise

    async def wait_until_ready(self, preparation_id: str, *, wait_timeout: float = 60) -> ReadyMaterial:
        ident = validate_id(preparation_id, self._api_key)
        deadline = _budget(wait_timeout)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise PreparationError('timeout', ident)
                try:
                    wait = min(10, remaining, self._timeout)
                    value, metadata = await self._send('GET', '/v1/materials/preparations/' + ident + '?wait=' + _wait(wait),
                        timeout=min(self._timeout, remaining), preparation=True)
                    value = parse_preparation(value, metadata, self._api_key, ident)
                    ready = _result(value)
                    if ready:
                        return ready
                    delay = max(.01, value.retry_after_ms / 1000)
                except (TransportError, HTTPError) as error:
                    if not _transient(error):
                        error.preparation_id = ident
                        raise
                    delay = random.uniform(.05, .15)
                except RayonError as error:
                    error.preparation_id = ident
                    raise
                await asyncio.sleep(min(delay, max(0, deadline - time.monotonic())))
        except asyncio.CancelledError:
            raise PreparationCancelledError(ident) from None

    async def prepare_and_wait(self, shape: ShapeRequest | FormShapeRequest, *, wait_timeout: float = 60) -> ReadyMaterial:
        _budget(wait_timeout)
        value = await self.prepare(shape)
        return _result(value) or await self.wait_until_ready(value.preparation_id, wait_timeout=wait_timeout)
