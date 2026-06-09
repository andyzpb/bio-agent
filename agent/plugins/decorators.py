from __future__ import annotations

import ast
import inspect
from types import UnionType
from typing import Any, Callable, Literal, Union, get_args, get_origin, get_type_hints

import docstring_parser

from agent.plugins.registry import (
    HandlerType,
    MetadataKind,
    PluginEventType,
    PluginHandlerMetadata,
    plugin_registry,
)


def _get_or_create_handler(
    func: Callable[..., Any],
    event_type: PluginEventType,
    handler_type: HandlerType,
    **kwargs: Any,
) -> PluginHandlerMetadata:
    # 1. 幂等：同一函数重复装饰时直接返回已有记录
    existing = plugin_registry._handlers.get_by_name(
        event_type, func.__name__, func.__module__
    )
    if existing:
        return existing
    # 2. 构建元数据并按 priority 插入全局 handler 列表
    md = PluginHandlerMetadata(
        kind=MetadataKind.LIFECYCLE,
        event_type=event_type,
        handler_type=handler_type,
        handler=func,
        handler_name=func.__name__,
        plugin_module_path=func.__module__,
        **kwargs,
    )
    plugin_registry._handlers.append(md)
    return md


def on_before_turn(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.BEFORE_TURN, HandlerType.GATE, **options)
        return func
    return deco


def on_before_reasoning(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.BEFORE_REASONING, HandlerType.GATE, **options)
        return func
    return deco


def on_before_step(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.BEFORE_STEP, HandlerType.GATE, **options)
        return func
    return deco


def on_prompt_render(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.PROMPT_RENDER, HandlerType.GATE, **options)
        return func
    return deco


def on_after_step(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.AFTER_STEP, HandlerType.TAP, **options)
        return func
    return deco


def on_after_reasoning(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.AFTER_REASONING, HandlerType.GATE, **options)
        return func
    return deco


def on_after_turn(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.AFTER_TURN, HandlerType.TAP, **options)
        return func
    return deco


def on_tool_call(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.BEFORE_TOOL_CALL, HandlerType.TAP, **options)
        return func
    return deco


def on_tool_result(**options: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        _ = _get_or_create_handler(func, PluginEventType.AFTER_TOOL_RESULT, HandlerType.TAP, **options)
        return func
    return deco


# on_tool_pre 装饰器：写入 MetadataKind.TOOL_HOOK，不走 EventBus，走 ToolExecutor pre_hook 链
def on_tool_pre(
    *,
    tool_name: str | None = None,
    **options: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        md = PluginHandlerMetadata(
            kind=MetadataKind.TOOL_HOOK,
            event_type=PluginEventType.PRE_TOOL,
            handler_type=None,
            handler=func,
            handler_name=func.__name__,
            plugin_module_path=func.__module__,
            hook_tool_name=tool_name,
            **options,
        )
        plugin_registry._handlers.append(md)
        return func
    return deco


# tool 装饰器：写入 MetadataKind.TOOL，不走 EventBus
def tool(
    name: str,
    *,
    risk: str = "read-write",
    always_on: bool = False,
    search_hint: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(func: Callable[..., Any]) -> Callable[..., Any]:
        # 校验签名：前两个参数必须是 self 和 event，否则 partial 绑定会静默错位
        params = list(inspect.signature(func).parameters.keys())
        if len(params) < 2 or params[0] != "self" or params[1] != "event":
            raise TypeError(
                f"@tool handler 前两个参数必须是 self 和 event: {func.__qualname__}"
            )
        schema = _derive_params_schema(func)
        md = PluginHandlerMetadata(
            kind=MetadataKind.TOOL,
            event_type=None,
            handler_type=None,
            handler=func,
            handler_name=func.__name__,
            plugin_module_path=func.__module__,
            tool_name=name,
            tool_schema=schema,
            tool_risk=risk,
            tool_always_on=always_on,
            tool_search_hint=search_hint,
        )
        plugin_registry._handlers.append(md)
        return func
    return deco


_PY_TO_JSON: dict[str, str] = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "dict": "object",
    "list": "array",
}


def _derive_params_schema(func: Callable[..., Any]) -> dict[str, Any]:
    sig = inspect.signature(func)
    try:
        type_hints = get_type_hints(func)
    except Exception:
        type_hints = {}
    docs = docstring_parser.parse(func.__doc__ or "")
    param_docs = {p.arg_name: p.description for p in docs.params}
    props: dict[str, Any] = {}
    required: list[str] = []
    for pn, p in sig.parameters.items():
        # 1. 跳过 self 和 event（生命周期占位参数，不进 schema）
        if pn in ("self", "event"):
            continue
        ann = type_hints.get(pn, p.annotation)
        prop = _annotation_to_json_schema(ann)
        if pn in param_docs:
            prop["description"] = param_docs[pn]
        props[pn] = prop
        # 2. 无默认值的参数进入 required
        if p.default is inspect.Parameter.empty:
            required.append(pn)
    return {"type": "object", "properties": props, "required": required}


def _annotation_to_json_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}
    if isinstance(annotation, str):
        return _string_annotation_to_json_schema(annotation)

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        value_type = _literal_json_type(values)
        if value_type:
            schema["type"] = value_type
        return schema

    if origin in (Union, UnionType):
        non_none = [arg for arg in args if arg is not type(None)]
        if len(non_none) == 1:
            return _annotation_to_json_schema(non_none[0])
        return {"type": "string"}

    if origin in (list, set, tuple):
        item_schema = (
            _annotation_to_json_schema(args[0])
            if args
            else {"type": "string"}
        )
        return {"type": "array", "items": item_schema}

    if origin is dict:
        return {"type": "object"}

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is dict:
        return {"type": "object"}
    if annotation is list:
        return {"type": "array", "items": {"type": "string"}}

    return {"type": _PY_TO_JSON.get(getattr(annotation, "__name__", ""), "string")}


def _string_annotation_to_json_schema(annotation: str) -> dict[str, Any]:
    text = annotation.strip()
    if " | " in text:
        non_none = [part.strip() for part in text.split("|") if part.strip() != "None"]
        if len(non_none) == 1:
            return _string_annotation_to_json_schema(non_none[0])
    if text.startswith("Literal[") and text.endswith("]"):
        inner = text[len("Literal[") : -1]
        try:
            loaded = ast.literal_eval(f"({inner},)")
        except Exception:
            return {"type": "string"}
        values = list(loaded if isinstance(loaded, tuple) else (loaded,))
        schema: dict[str, Any] = {"enum": values}
        value_type = _literal_json_type(values)
        if value_type:
            schema["type"] = value_type
        return schema
    if text.startswith("list[") and text.endswith("]"):
        return {
            "type": "array",
            "items": _string_annotation_to_json_schema(text[len("list[") : -1]),
        }
    if text.startswith("dict[") or text == "dict":
        return {"type": "object"}
    return {"type": _PY_TO_JSON.get(text, "string")}


def _literal_json_type(values: list[Any]) -> str:
    non_none = [value for value in values if value is not None]
    if not non_none:
        return "string"
    if all(isinstance(value, str) for value in non_none):
        return "string"
    if all(isinstance(value, bool) for value in non_none):
        return "boolean"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_none):
        return "integer"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_none):
        return "number"
    return ""
