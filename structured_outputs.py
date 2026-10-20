"""Local checks for OpenAI's supported strict JSON Schema subset.

This catches structural and size errors without spending an API request.
It is not an implementation of the provider's grammar compiler. In
particular, passing these checks cannot guarantee remote acceptance.
Limits: https://developers.openai.com/api/docs/guides/structured-outputs
"""
from __future__ import annotations

import jsonschema


def check_response_schema(schema):
    jsonschema.Draft202012Validator.check_schema(schema)
    if schema.get('type') != 'object' or 'anyOf' in schema:
        raise ValueError('Schemat odpowiedzi musi mieć obiekt w korzeniu, bez anyOf.')
    stats = {'properties': 0, 'enum_values': 0, 'string_chars': 0}
    definitions = schema.get('$defs', {})

    def visit(node, path):
        if not isinstance(node, dict):
            raise ValueError(f'{path}: wymagany schemat obiektowy.')
        forbidden = {'allOf', 'oneOf', 'not', 'if', 'then', 'else', 'dependentRequired', 'dependentSchemas'} & node.keys()
        if forbidden:
            raise ValueError(f'{path}: nieobsługiwane elementy schematu: {sorted(forbidden)}.')
        if node.get('type') == 'object':
            properties = node.get('properties', {})
            if node.get('additionalProperties') is not False or set(node.get('required', [])) != set(properties):
                raise ValueError(f'{path}: wszystkie pola muszą być required i additionalProperties=false.')
            stats['properties'] += len(properties)
            stats['string_chars'] += sum(map(len, properties))
            for key, child in properties.items():
                visit(child, path + '.properties.' + key)
        if '$ref' in node:
            ref = node['$ref']
            if not ref.startswith('#/$defs/') or ref[len('#/$defs/'):] not in definitions:
                raise ValueError(f'{path}: nieznane odwołanie schematu {ref}.')
        if 'enum' in node:
            values = node['enum']
            chars = sum(len(v) for v in values if isinstance(v, str))
            stats['enum_values'] += len(values)
            stats['string_chars'] += chars
            if len(values) > 250 and chars > 15000:
                raise ValueError(f'{path}: zbyt duża lista tekstowych wartości enum.')
        if isinstance(node.get('const'), str):
            stats['string_chars'] += len(node['const'])
        if 'items' in node:
            visit(node['items'], path + '.items')
        for index, child in enumerate(node.get('anyOf', [])):
            visit(child, path + f'.anyOf.{index}')

    visit(schema, '$')
    for key, definition in definitions.items():
        stats['string_chars'] += len(key)
        visit(definition, '$defs.' + key)
    if stats['properties'] > 5000 or stats['enum_values'] > 1000 or stats['string_chars'] > 120000:
        raise ValueError(f'Schemat odpowiedzi przekracza limity OpenAI: {stats}.')
    return stats
