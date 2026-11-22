"""Modal provider implementation of the Enterprise managed sandbox contract."""
import asyncio
import json
import logging
import os
import re
import secrets
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator, ClassVar

import httpx
import modal
from fastapi import Request
from pydantic import Field, SecretStr

from openhands.app_server.errors import SandboxDeleteRetryError, SandboxError
from openhands.app_server.sandbox.managed_sandbox_service import (
    ManagedSandboxService, ManagedSandboxServiceInjector, ProviderOutcome,
)
from openhands.app_server.sandbox.modal_preview import preview_domain, preview_origin
from openhands.app_server.sandbox.preset_sandbox_spec_service import PresetSandboxSpecService
from openhands.app_server.sandbox.sandbox_models import (
    AGENT_SERVER, WORKER_1, ExposedUrl, SandboxInfo, SandboxPage, SandboxRecord,
    SandboxStartedBy, SandboxStatus,
)
from openhands.app_server.sandbox.sandbox_service import SandboxService
from openhands.app_server.sandbox.sandbox_spec_models import SandboxSpecInfo
from openhands.app_server.sandbox.sandbox_spec_service import (
    SandboxSpecService, SandboxSpecServiceInjector, resolve_sandbox_spec,
)
from openhands.app_server.sandbox.sandbox_store import (
    LifecycleState, StoredSandbox, get_credential_org_id,
    get_stored_sandbox_by_session_api_key, hash_session_api_key, require_user_id,
    sandbox_started_by, search_stored_sandboxes,
)
from openhands.app_server.services.injector import InjectorState

BACKEND = 'modal'
SPEC_ID = 'modal-agent-server'
LOGGER = logging.getLogger(__name__)


async def get_guest(provider_id: str) -> modal.Sandbox:
    return await modal.Sandbox.from_id.aio(provider_id)


@dataclass
class ModalSandboxService(ManagedSandboxService):
    backend: ClassVar[str] = BACKEND
    sandbox_spec_service: SandboxSpecService
    app_origin: str
    gateway: str

    def _exposed_urls(self, sandbox_id: str) -> list[ExposedUrl]:
        urls = [ExposedUrl(
            name=AGENT_SERVER, port=8000, url=f'{self.gateway}/{sandbox_id}/8000',
        )]
        domain = preview_domain(self.app_origin)
        if domain:
            urls.append(ExposedUrl(
                name=WORKER_1, port=8011, url=preview_origin(domain, sandbox_id) + '/',
            ))
        return urls

    async def _info(self, row: StoredSandbox) -> SandboxInfo:
        if row.lifecycle_state == LifecycleState.PAUSED:
            status = SandboxStatus.PAUSED
        elif not row.provider_resource_id:
            status = SandboxStatus.STARTING
        else:
            try:
                guest = await get_guest(row.provider_resource_id)
                status = (
                    SandboxStatus.RUNNING if await guest.poll.aio() is None
                    else SandboxStatus.MISSING
                )
            except modal.exception.NotFoundError:
                status = SandboxStatus.MISSING
            except modal.exception.Error:
                status = SandboxStatus.STARTING
        running = status == SandboxStatus.RUNNING
        return SandboxInfo(
            id=row.id,
            created_by_user_id=row.created_by_user_id,
            credential_org_id=row.credential_org_id,
            started_by=sandbox_started_by(row),
            sandbox_spec_id=row.sandbox_spec_id,
            supports_runtime_pause=True,
            status=status,
            session_api_key=row.session_api_key.get_secret_value()
            if running and row.session_api_key else None,
            exposed_urls=self._exposed_urls(row.id) if running else [],
            created_at=row.created_at,
        )

    async def search_sandboxes(self, page_id=None, limit=100):
        page = await search_stored_sandboxes(
            self.db_session, self.user_context, self.backend, page_id, limit,
        )
        return SandboxPage(
            items=[await self._info(row) for row in page.items],
            next_page_id=page.next_page_id,
        )

    async def batch_get_sandboxes(self, sandbox_ids):
        rows = [await self._get_stored_sandbox(sid) for sid in sandbox_ids]
        async def as_info(row):
            return await self._info(row) if row else None
        return list(await asyncio.gather(*(as_info(row) for row in rows)))

    async def get_sandbox(self, sandbox_id):
        row = await self._get_stored_sandbox(sandbox_id)
        return await self._info(row) if row else None

    async def _row_for_key(self, key):
        return await get_stored_sandbox_by_session_api_key(
            self.db_session, self.user_context, self.backend, key,
        )

    async def get_sandbox_by_session_api_key(self, session_api_key):
        row = await self._row_for_key(session_api_key)
        return await self._info(row) if row else None

    async def get_sandbox_record_by_session_api_key(self, session_api_key):
        row = await self._row_for_key(session_api_key)
        if row is None:
            return None
        return SandboxRecord(
            id=row.id, created_by_user_id=row.created_by_user_id,
            credential_org_id=row.credential_org_id,
        )

    async def _check_agent_server_alive(self, sandbox, httpx_client):
        if not sandbox.session_api_key:
            return False
        try:
            response = await httpx_client.get(
                self._get_agent_server_url(sandbox).rstrip('/') + '/alive',
                headers={'X-Session-API-Key': sandbox.session_api_key},
                timeout=5,
            )
            return response.is_success
        except httpx.HTTPError:
            return False

    async def _ready(self, guest, key):
        tunnel = (await guest.tunnels.aio(timeout=90))[8000]
        async with asyncio.timeout(90):
            while True:
                try:
                    response = await self.httpx_client.get(
                        tunnel.url + '/api/conversations/search',
                        headers={'X-Session-API-Key': key},
                        timeout=4,
                    )
                    if response.status_code == 200:
                        return
                except httpx.TransportError:
                    pass
                if await guest.poll.aio() is not None:
                    raise SandboxError('Modal Agent Server stopped during startup')
                await asyncio.sleep(.4)

    async def start_sandbox(
        self,
        sandbox_spec_id=None,
        sandbox_id=None,
        extra_env=None,
        started_by=SandboxStartedBy.SANDBOX_API,
    ):
        user_id = await require_user_id(self.user_context)
        org_id = await get_credential_org_id(self.user_context)
        spec = await resolve_sandbox_spec(
            sandbox_spec_id, await self.user_context.get_default_sandbox_spec_id(),
            self.sandbox_spec_service, LOGGER,
        )
        await self.pause_old_sandboxes(self.max_num_sandboxes - 1)
        fixed = os.getenv('MODAL_PILOT_SANDBOX_ID')
        sid = sandbox_id or fixed or secrets.token_hex(16)
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', sid):
            raise SandboxError('Invalid Modal sandbox name')
        # This pilot admits a single pre-certified preview origin per trial.
        if fixed and sid != fixed:
            raise SandboxError('Use the certified Modal pilot sandbox ID')
        if await self._get_stored_sandbox(sid):
            raise SandboxError('The Modal pilot sandbox already exists')
        key = secrets.token_urlsafe(32)
        env = dict(spec.initial_env)
        env.update(extra_env or {})
        env.update(self._lifecycle_env())
        env.update({
            'OH_CONVERSATION_RUNTIME': 'local',
            'OH_LEASE_TTL_SECONDS': '0',
            'OH_WEB_URL': self.app_origin,
            'OH_WEBHOOKS': json.dumps([{
                'base_url': self.app_origin + '/api/v1/webhooks',
                'event_buffer_size': 1,
            }]),
            'OH_ALLOW_CORS_ORIGINS': '["' + self.app_origin + '"]',
        })
        proxy = Path(__file__).with_name('modal_guest_preview.py').read_text()
        command = (
            'mkdir -p /workspace/project; python3 -c ' + shlex.quote(proxy)
            + ' & exec /usr/local/bin/openhands-agent-server --host 0.0.0.0 --port 8000'
        )
        app = await modal.App.lookup.aio(os.environ['MODAL_PILOT_APP'], create_if_missing=False)
        guest = await modal.Sandbox.create.aio(
            'bash', '-ec', command,
            app=app, name='oh-' + sid, runtime='vm',
            image=modal.Image.from_registry(
                'ghcr.io/openhands/agent-server:1.62.0-python',
            ).dockerfile_commands(['ENTRYPOINT []']),
            env=env, secrets=[modal.Secret.from_dict({'OH_SESSION_API_KEYS_0': key})],
            timeout=1200, cpu=2, memory=2048, encrypted_ports=[8000, 8011],
            _experimental_enable_snapshot=True,
        )
        try:
            await self._ready(guest, key)
            row = self._new_stored_sandbox(
                id=sid, created_by_user_id=user_id, credential_org_id=org_id,
                started_by=started_by.value, sandbox_spec_id=spec.id,
                session_api_key=SecretStr(key), session_api_key_hash=hash_session_api_key(key),
                provider_resource_id=guest.object_id,
            )
            self.db_session.add(row)
            await self.db_session.flush()
            return await self._info(row)
        except BaseException:
            await asyncio.shield(guest.terminate.aio(wait=True))
            raise

    async def _pause_at_provider(self, row):
        if row.lifecycle_state == LifecycleState.PAUSED and row.modal_snapshot_id:
            return ProviderOutcome.ALREADY_DONE
        if not row.provider_resource_id:
            return ProviderOutcome.FAILED
        guest = await get_guest(row.provider_resource_id)
        if await guest.poll.aio() is not None:
            return ProviderOutcome.FAILED
        snapshot = await guest._experimental_snapshot.aio()
        row.modal_snapshot_id = snapshot.object_id
        return ProviderOutcome.CHANGED

    async def _resume_at_provider(self, row):
        if row.lifecycle_state == LifecycleState.RUNNING:
            return (
                ProviderOutcome.ALREADY_DONE
                if row.provider_resource_id and await (
                    await get_guest(row.provider_resource_id)
                ).poll.aio() is None else ProviderOutcome.FAILED
            )
        if not row.modal_snapshot_id or not row.session_api_key:
            return ProviderOutcome.FAILED
        snapshot = await modal.SandboxSnapshot.from_id.aio(row.modal_snapshot_id)
        guest = await modal.Sandbox._experimental_from_snapshot.aio(snapshot)
        try:
            await self._ready(guest, row.session_api_key.get_secret_value())
        except BaseException:
            await asyncio.shield(guest.terminate.aio(wait=True))
            raise
        row.provider_resource_id = guest.object_id
        return ProviderOutcome.CHANGED

    async def _delete_at_provider(self, row):
        if not row.provider_resource_id:
            return
        try:
            guest = await get_guest(row.provider_resource_id)
            await guest.terminate.aio(wait=True)
        except modal.exception.NotFoundError:
            return
        except modal.exception.Error as exc:
            raise SandboxDeleteRetryError('Modal sandbox termination failed') from exc


class ModalSandboxServiceInjector(ManagedSandboxServiceInjector):
    backend: ClassVar[str] = BACKEND
    gateway_base_url: str = Field(
        default_factory=lambda: os.environ['MODAL_GATEWAY_URL'].rstrip('/')
    )
    internal_url: str | None = Field(
        default_factory=lambda: os.getenv('MODAL_GATEWAY_INTERNAL_URL')
    )

    async def inject(
        self, state: InjectorState, request: Request | None = None,
    ) -> AsyncGenerator[SandboxService, None]:
        from openhands.app_server.config import (
            get_db_session, get_global_config, get_httpx_client,
            get_sandbox_spec_service, get_user_context,
        )
        async with (
            get_user_context(state, request) as user,
            get_db_session(state, request) as db,
            get_httpx_client(state, request) as http,
            get_sandbox_spec_service(state, request) as specs,
        ):
            yield ModalSandboxService(
                user_context=user, db_session=db, httpx_client=http,
                max_num_sandboxes=1, sandbox_spec_service=specs,
                app_origin=get_global_config().web_url or '',
                gateway=self.gateway_base_url,
                lifecycle=self.lifecycle,
            )


class ModalSandboxSpecServiceInjector(SandboxSpecServiceInjector):
    async def inject(self, state, request=None):
        yield PresetSandboxSpecService(specs=[
            SandboxSpecInfo(id=SPEC_ID, command=None, working_dir='/workspace/project'),
        ])
