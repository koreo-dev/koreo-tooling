"""Context-aware completion provider for Koreo language server"""

import re

from koreo import cache
from lsprotocol import types
from pygls.workspace import TextDocument

from koreo_tooling.indexing.semantics import SemanticAnchor
from koreo_tooling.langserver.rangers import block_range_extract

# CEL function signatures for better completions
CEL_FUNCTIONS = {
    "size": "size(collection) -> int",
    "has": "has(field) -> bool",
    "all": "all(list, predicate) -> bool",
    "exists": "exists(list, predicate) -> bool",
    "exists_one": "exists_one(list, predicate) -> bool",
    "map": "map(list, transform) -> list",
    "filter": "filter(list, predicate) -> list",
    "matches": "matches(pattern) -> bool",
    "contains": "contains(substring) -> bool",
    "startsWith": "startsWith(prefix) -> bool",
    "endsWith": "endsWith(suffix) -> bool",
}

# Common Koreo patterns
KOREO_PATTERNS = {
    "workflow_step": {
        "label": "step",
        "insert_text": """- label: ${1:step_name}
  ref:
    kind: ${2:ValueFunction}
    name: ${3:function_name}
  inputs:
    ${4:input_name}: =${5:expression}""",
        "detail": "Workflow step with function reference"
    },
    "value_function": {
        "label": "ValueFunction",
        "insert_text": """apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: ${1:function_name}
spec:
  return:
    ${2:output_name}: =${3:expression}""",
        "detail": "Create a new ValueFunction"
    },
    "resource_function": {
        "label": "ResourceFunction", 
        "insert_text": """apiVersion: koreo.dev/v1beta1
kind: ResourceFunction
metadata:
  name: ${1:function_name}
spec:
  apiConfig:
    apiVersion: ${2:apps/v1}
    kind: ${3:Deployment}
  resource:
    metadata:
      name: =${4:inputs.name}""",
        "detail": "Create a new ResourceFunction"
    },
}


def get_completion_context(doc: TextDocument, position: types.Position) -> tuple[str, str, int]:
    """Get the context for completion at the given position"""
    line = doc.lines[position.line]
    prefix = line[:position.character]
    
    # Check if we're in a CEL expression
    cel_match = re.search(r'=\s*([^=]*)$', prefix)
    if cel_match:
        return "cel", cel_match.group(1).strip(), cel_match.start(1)
    
    # Check if we're typing a reference
    ref_match = re.search(r'(kind|name):\s*(\w*)$', prefix)
    if ref_match:
        return f"ref_{ref_match.group(1)}", ref_match.group(2), ref_match.start(2)
    
    # Check if we're in inputs section
    if re.search(r'inputs:\s*$', prefix):
        return "inputs", "", position.character
        
    # Check for step reference in CEL expressions (=step_name.property)
    step_ref_match = re.search(r'=\s*(\w+)\.(\w*)$', prefix)
    if step_ref_match:
        return "step_property", step_ref_match.group(2), step_ref_match.start(2)
    
    # Check for step name completion in CEL expressions (=step_)
    step_name_match = re.search(r'=\s*(\w*)$', prefix)
    if step_name_match and not cel_match:
        return "step_name", step_name_match.group(1), step_name_match.start(1)
    
    # Default context
    return "general", prefix.strip().split()[-1] if prefix.strip() else "", 0


def get_cel_completions(prefix: str) -> list[types.CompletionItem]:
    """Get CEL-specific completions"""
    items = []
    
    # Add CEL functions
    for func, signature in CEL_FUNCTIONS.items():
        if func.startswith(prefix.lower()):
            items.append(types.CompletionItem(
                label=func,
                kind=types.CompletionItemKind.Function,
                detail=signature,
                insert_text=f"{func}(${{1}})",
                insert_text_format=types.InsertTextFormat.Snippet,
            ))
    
    # Add common CEL keywords
    for keyword in ["true", "false", "null", "in"]:
        if keyword.startswith(prefix.lower()):
            items.append(types.CompletionItem(
                label=keyword,
                kind=types.CompletionItemKind.Keyword,
            ))
    
    # Add common variables
    for var in ["inputs", "parent", "self", "locals"]:
        if var.startswith(prefix.lower()):
            items.append(types.CompletionItem(
                label=var,
                kind=types.CompletionItemKind.Variable,
                detail=f"Access {var} object",
                insert_text=f"{var}.",
                command=types.Command(
                    title="Trigger completion",
                    command="editor.action.triggerSuggest"
                ) if var in ["inputs", "locals", "parent", "self"] else None
            ))
    
    return items


def get_reference_completions(ref_type: str, prefix: str) -> list[types.CompletionItem]:
    """Get completions for references (kind/name)"""
    items = []
    
    if ref_type == "ref_kind":
        # Suggest resource kinds
        for kind in ["ValueFunction", "ResourceFunction", "Workflow"]:
            if kind.lower().startswith(prefix.lower()):
                items.append(types.CompletionItem(
                    label=kind,
                    kind=types.CompletionItemKind.Class,
                ))
    
    elif ref_type == "ref_name":
        # Suggest cached resources
        for cache_type, cached in cache.__CACHE.items():
            for resource_key, _ in cached.items():
                if resource_key.startswith(prefix):
                    items.append(types.CompletionItem(
                        label=resource_key.split(":")[-1],  # Extract just the name
                        kind=types.CompletionItemKind.Reference,
                        detail=f"{cache_type}",
                    ))
    
    return items


def get_step_name_completions(workflow_anchor: SemanticAnchor | None, prefix: str) -> list[types.CompletionItem]:
    """Get completions for step names in CEL expressions (=step_name)"""
    items = []
    
    if not workflow_anchor:
        return items
    
    # Extract step labels from the workflow
    steps_block = block_range_extract(
        search_key="steps",
        search_nodes=workflow_anchor.children,
        anchor=workflow_anchor,
    )
    
    if steps_block and hasattr(steps_block, 'children'):
        for step in steps_block.children:
            label_block = block_range_extract(
                search_key="label",
                search_nodes=step.children if hasattr(step, 'children') else [],
                anchor=workflow_anchor,
            )
            if label_block and hasattr(label_block, 'value'):
                label = label_block.value
                if label.startswith(prefix):
                    items.append(types.CompletionItem(
                        label=label,
                        kind=types.CompletionItemKind.Variable,
                        detail="Step reference",
                        insert_text=f"{label}.",
                        command=types.Command(
                            title="Trigger completion",
                            command="editor.action.triggerSuggest"
                        )
                    ))
    
    return items


def get_step_property_completions(workflow_anchor: SemanticAnchor | None, step_name: str, prefix: str) -> list[types.CompletionItem]:
    """Get completions for step properties (=step_name.property)"""
    items = []
    
    # Common step output properties based on function types
    common_properties = [
        ("status", "Step execution status"),
        ("error", "Error information if step failed"),
        ("metadata", "Step metadata"),
        ("result", "Step return value (ValueFunction)"),
        ("output", "Step output (ResourceFunction)"),
        ("resource", "Created/managed resource (ResourceFunction)"),
        ("name", "Resource name"),
        ("namespace", "Resource namespace"),
    ]
    
    for prop, detail in common_properties:
        if prop.startswith(prefix.lower()):
            items.append(types.CompletionItem(
                label=prop,
                kind=types.CompletionItemKind.Property,
                detail=detail,
                insert_text=prop,
            ))
    
    return items


def get_pattern_completions(context: str, prefix: str) -> list[types.CompletionItem]:
    """Get pattern-based completions"""
    items = []
    
    for _pattern_id, pattern in KOREO_PATTERNS.items():
        if pattern["label"].lower().startswith(prefix.lower()):
            items.append(types.CompletionItem(
                label=pattern["label"],
                kind=types.CompletionItemKind.Snippet,
                detail=pattern["detail"],
                insert_text=pattern["insert_text"],
                insert_text_format=types.InsertTextFormat.Snippet,
            ))
    
    return items


def provide_completions(
    doc: TextDocument,
    position: types.Position,
    semantic_anchor: SemanticAnchor | None = None
) -> types.CompletionList:
    """Main completion provider function"""
    context, prefix, start_col = get_completion_context(doc, position)
    items = []
    
    if context == "cel":
        items.extend(get_cel_completions(prefix))
    elif context.startswith("ref_"):
        items.extend(get_reference_completions(context, prefix))
    elif context == "step_name":
        items.extend(get_step_name_completions(semantic_anchor, prefix))
    elif context == "step_property":
        # Extract step name from the line to provide relevant property completions
        line = doc.lines[position.line]
        step_match = re.search(r'=(\w+)\.', line[:position.character])
        step_name = step_match.group(1) if step_match else ""
        items.extend(get_step_property_completions(semantic_anchor, step_name, prefix))
    elif context == "inputs":
        # Suggest common input patterns
        items.append(types.CompletionItem(
            label="input_name",
            kind=types.CompletionItemKind.Property,
            insert_text="${1:name}: =${2:expression}",
            insert_text_format=types.InsertTextFormat.Snippet,
        ))
    else:
        # General completions
        items.extend(get_pattern_completions(context, prefix))
        
        # Add cached resources as fallback
        for cache_type, cached in cache.__CACHE.items():
            for resource_key, _ in cached.items():
                if prefix in resource_key:
                    items.append(types.CompletionItem(
                        label=resource_key,
                        kind=types.CompletionItemKind.Reference,
                        detail=f"{cache_type}",
                    ))
    
    return types.CompletionList(
        is_incomplete=len(items) > 100,  # Mark as incomplete if too many items
        items=items[:100]  # Limit to 100 items
    )