from __future__ import annotations

import json
import os
from json.decoder import JSONDecodeError
from typing import Any, Dict, Iterator, List

import sublime

from . import jl_utility as jl


class Cacher:
    def __init__(self, name: str | None = None) -> None:
        cache_dir = sublime.cache_path()
        plugin_cache_dir = os.path.join(cache_dir, 'OpenAI completion')
        if not os.path.exists(plugin_cache_dir):
            os.makedirs(plugin_cache_dir)

        # Create the file path to store the data
        self.history_file = os.path.join(
            plugin_cache_dir,
            '{file_name}chat_history.jl'.format(file_name=name + '_' if name else ''),
        )
        self.current_model_file = os.path.join(
            plugin_cache_dir,
            '{file_name}current_assistant.json'.format(file_name=name + '_' if name else ''),
        )
        self.tokens_count_file = os.path.join(
            plugin_cache_dir,
            '{file_name}tokens_count.json'.format(file_name=name + '_' if name else ''),
        )

    def check_and_create(self, path: str):
        if not os.path.isfile(path):
            open(path, 'w').close()

    def append_tokens_count(self, data: Dict[str, int]):
        try:
            with open(self.tokens_count_file, 'r') as file:
                existing_data: Dict[str, int] = json.load(file)
        except (FileNotFoundError, JSONDecodeError):
            existing_data = {
                'prompt_tokens': 0,
                'completion_tokens': 0,
                'total_tokens': 0,
            }

        for key, value in data.items():
            if key in existing_data:
                existing_data[key] += value
            else:
                existing_data[key] = value

        with open(self.tokens_count_file, 'w') as file:
            json.dump(existing_data, file)

    def reset_tokens_count(self):
        with open(self.tokens_count_file, 'w') as _:
            pass  # Truncate the file by opening it in 'w' mode and doing nothing

    def read_tokens_count(self) -> Dict[str, int] | None:
        self.check_and_create(self.tokens_count_file)
        with open(self.tokens_count_file, 'r') as file:
            try:
                data: Dict[str, int] | None = json.load(file)
            except JSONDecodeError:
                data = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
                return data
        return data

    def save_model(self, data: Dict[str, Any]):
        with open(self.current_model_file, 'w') as file:
            json.dump(data, file)

    def read_model(self) -> Dict[str, Any] | None:
        self.check_and_create(self.current_model_file)
        with open(self.current_model_file, 'r') as file:
            try:
                data: Dict[str, Any] | None = json.load(file)
            except JSONDecodeError:
                # TODO: Handle this state, but keep in mind
                # that it's completely legal to being a file empty for some (yet unspecified) state
                print('Empty file I belive')
                return None
        return data

    def read_all(self) -> List[Dict[str, str]]:
        self.check_and_create(self.history_file)
        json_objects: List[Dict[str, str]] = []
        reader: Iterator[Dict[str, str]] = jl.reader(self.history_file)
        for json_object in reader:
            json_objects.append(json_object)

        return json_objects

    def read_last(self, number: int) -> List[Dict[str, str]]:
        self.check_and_create(self.history_file)
        json_objects: List[Dict[str, str]] = []

        with open(self.history_file, 'r', encoding='utf-8') as file:
            lines = file.readlines()

        last_n_lines = lines[-number:]  # Get the last n lines

        for line in last_n_lines:
            try:
                json_object: Dict[str, str] = json.loads(line)
                json_objects.append(json_object)
            except json.JSONDecodeError:
                # FIXME: raise an error here that should be handled somewhere on top of the file
                print('Error decoding JSON from line:', line)
                pass

        return json_objects

    def append_to_cache(self, cache_lines: List[Dict[str, str]]):
        # Create a new JSON Lines writer for output.jl
        writer = jl.writer(self.history_file)
        next(writer)
        for line in cache_lines:
            writer.send(line)

    def drop_first(self, number=4):
        self.check_and_create(self.history_file)
        # Read all lines from the JSON Lines file
        with open(self.history_file, 'r') as file:
            lines = file.readlines()

        # Remove the specified number of lines from the beginning
        lines = lines[number:]

        # Write the remaining lines back to the cache file
        with open(self.history_file, 'w') as file:
            file.writelines(lines)

    def drop_all(self):
        with open(self.history_file, 'w') as _:
            pass  # Truncate the file by opening it in 'w' mode and doing nothing
