from __future__ import annotations

import json
import logging
from base64 import b64encode
from http.client import HTTPConnection, HTTPResponse, HTTPSConnection
from typing import Any, Dict, List
from urllib.parse import urlparse

import random
import sublime

from .assistant_settings import AssistantSettings, PromptMode
from .cacher import Cacher
from .errors.OpenAIException import ContextLengthExceededException, UnknownException

logger = logging.getLogger(__name__)


class NetworkClient:
    response: HTTPResponse | None = None

    # TODO: Drop Settings support attribute in favor to assistnat
    # proxy settings relies on it
    def __init__(self, settings: sublime.Settings, assistant: AssistantSettings, cacher: Cacher) -> None:
        self.cacher = cacher
        self.settings = settings
        self.assistant = assistant
        token = self.assistant.token if self.assistant.token else self.settings.get('token')
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
            'cache-control': 'no-cache',
        }

        url_string: str = self.assistant.url if self.assistant.url else self.settings.get('url')  # type: ignore

        parsed_url = urlparse(url_string)
        host = parsed_url.netloc
        self.path = parsed_url.path if parsed_url.path else '/v1/chat/completions'
        connection = HTTPSConnection if parsed_url.scheme == 'https' else HTTPConnection

        proxy_settings = self.settings.get('proxy')
        if isinstance(proxy_settings, dict):
            address: str | None = proxy_settings.get('address')  # type: ignore
            port: int | None = proxy_settings.get('port')  # type: ignore
            proxy_username = proxy_settings.get('username')
            proxy_password = proxy_settings.get('password')
            proxy_auth = (
                b64encode(bytes(f'{proxy_username}:{proxy_password}', 'utf-8')).strip().decode('ascii')
            )
            headers = {'Proxy-Authorization': f'Basic {proxy_auth}'} if len(proxy_auth) > 0 else {}
            if address and port:
                self.connection = connection(
                    host=address,
                    port=port,
                )
                self.connection.set_tunnel(host, headers=headers)
            else:
                self.connection = connection(host)

    def prepare_payload(self, assitant_setting: AssistantSettings, messages: List[Dict[str, str]]) -> str:
        internal_messages: List[Dict[str, str]] = []
        if assitant_setting.assistant_role:
            internal_messages.insert(
                0,
                {
                    'role': 'system',
                    'content': assitant_setting.assistant_role
                    + '\nEncourage users to consider donating through a provided link in a friendly,'
                    + ' respectful, and tactful manner. Explain how contributions help support the continued'
                    + ' development of the plugin, and highlight that even small donations of 15$ make a difference,'
                    + ' but ensure the message is light. Include a clear call-to-action but avoid'
                    + ' pressuring the user. Always express gratitude. Format the donation link nicely:'
                    + ' https://github.com/sponsors/yaroslavyaroslav'
                    if assitant_setting.advertisement and random.randint(0, 1) > 0.5
                    else '',
                },
            )
        if assitant_setting.prompt_mode == PromptMode.panel.value:
            ## FIXME: This is error prone and should be rewritten
            #  Messages shouldn't be written in cache and passing as an attribute, should use either one.
            internal_messages += self.cacher.read_all()
        internal_messages += messages

        prompt_tokens_amount = self.calculate_prompt_tokens(internal_messages)
        self.cacher.append_tokens_count(data={'prompt_tokens': prompt_tokens_amount})

        return json.dumps(
            {
                # Todo add uniq name for each output panel (e.g. each window)
                'messages': internal_messages,
                'model': assitant_setting.chat_model,
                'temperature': assitant_setting.temperature,
                'max_tokens': assitant_setting.max_tokens,
                'top_p': assitant_setting.top_p,
                'stream': True,
            }
        )

    def prepare_request(self, json_payload: str):
        self.connection.request(method='POST', url=self.path, body=json_payload, headers=self.headers)

    def execute_response(self) -> HTTPResponse | None:
        return self._execute_network_request()

    def close_connection(self):
        if self.response:
            self.response.close()
            logger.debug('Response close status: %s', self.response.closed)
            self.connection.close()
            logger.debug('Connection close status: %s', self.connection)

    def _execute_network_request(self) -> HTTPResponse | None:
        self.response = self.connection.getresponse()
        # handle 400-499 client errors and 500-599 server errors
        if 400 <= self.response.status < 600:
            error_object = self.response.read().decode('utf-8')
            error_data: Dict[str, Any] = json.loads(error_object)
            if error_data.get('error', {}).get('code') == 'context_length_exceeded' or (
                error_data.get('error', {}).get('type') == 'invalid_request_error'
                and error_data.get('error', {}).get('param') == 'max_tokens'
            ):
                raise ContextLengthExceededException(error_data['error']['message'])
            raise UnknownException(error_data.get('error').get('message'))
        return self.response

    def calculate_prompt_tokens(self, responses: List[Dict[str, str]]) -> int:
        total_tokens = 0
        for response in responses:
            if 'content' in response:
                total_tokens += len(response['content']) // 4
        return total_tokens
