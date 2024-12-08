from __future__ import annotations


from .semantics import Modifier, SemanticStructure


VALUE = "."
ALL = "*"


def step_path_indexer(value) -> str:
    try:
        return (
            f"Step:{''.join(name.value for key, name in value if key.value == 'label')}"
        )
    except Exception as err:
        raise Exception(f"Failed to process '{value}', with {err}")


_api_version: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        index_key_fn=lambda value: f"api_version",
        type="namespace",
    )
)

_kind: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        index_key_fn=lambda value: f"kind",
        type="type",
    ),
)

_namespace: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        type="namespace",
    ),
)

_function_ref: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure=SemanticStructure(
        sub_structure={
            "name": SemanticStructure(
                type="property",
                sub_structure=SemanticStructure(
                    index_key_fn=lambda value: f"Function:{value}:ref",
                    type="function",
                ),
            ),
        },
    ),
)

_workflow_ref: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure={
        "name": SemanticStructure(
            type="property",
            sub_structure=SemanticStructure(
                index_key_fn=lambda value: f"Workflow:{value}:ref",
                type="class",
            ),
        ),
    },
)

_managed_resource: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure={
        "apiVersion": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="namespace"),
        ),
        "kind": SemanticStructure(
            type="parameter", sub_structure=SemanticStructure(type="type")
        ),
        "plural": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(
                type="number",
            ),
        ),
        "namespaced": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="number"),
        ),
    },
)

_behavior: SemanticStructure = SemanticStructure(
    sub_structure={
        "load": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
        "create": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(
                type="number",
            ),
        ),
        "update": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
        "delete": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="enumMember"),
        ),
    },
)

_function_inputs: SemanticStructure = SemanticStructure(
    type="property",
    local_key_fn=lambda value: "inputs",
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: "InputValues",
        sub_structure={
            ALL: SemanticStructure(
                local_key_fn=lambda value: f"input:{value}", type="variable"
            )
        },
    ),
)

SEMANTIC_TYPE_STRUCTURE: dict[str, SemanticStructure] = {
    "Function": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure={
                    "name": SemanticStructure(
                        sub_structure=SemanticStructure(
                            index_key_fn=lambda value: f"Function:{value}:def",
                            type="function",
                            modifier=[Modifier.definition],
                        ),
                    ),
                    "namespace": _namespace,
                },
            ),
            "spec": SemanticStructure(
                sub_structure={
                    "staticResource": SemanticStructure(
                        type="property",
                        sub_structure={
                            "managedResource": _managed_resource,
                            "behavior": _behavior,
                        },
                    ),
                    "dynamicResource": SemanticStructure(
                        type="property",
                        sub_structure={
                            "key": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(
                                    type="function",
                                    index_key_fn=lambda value: (
                                        None
                                        if value.startswith("=")
                                        else f"ResourceTemplate:{value}:ref"
                                    ),
                                ),
                            ),
                        },
                    ),
                    "inputValidators": SemanticStructure(
                        sub_structure={
                            "type": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(type="class"),
                            ),
                            "message": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(type="string"),
                            ),
                            "test": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(type="string"),
                            ),
                        },
                    ),
                    "outcome": SemanticStructure(
                        sub_structure={
                            "okValue": SemanticStructure(
                                sub_structure=SemanticStructure(type="string")
                            ),
                        },
                    ),
                },
            ),
        },
    ),
    "Workflow": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"Workflow:{value}:def",
                                type="class",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                sub_structure={
                    "crdRef": SemanticStructure(
                        type="typeParameter",
                        sub_structure={
                            "apiGroup": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="namespace"),
                            ),
                            "version": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="string"),
                            ),
                            "kind": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="class"),
                            ),
                        },
                    ),
                    "steps": SemanticStructure(
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                local_key_fn=step_path_indexer,
                                sub_structure={
                                    "label": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: f"label:{value}",
                                            type="event",
                                            modifier=[Modifier.definition],
                                        ),
                                    ),
                                    "functionRef": _function_ref,
                                    "workflowRef": _workflow_ref,
                                    "inputs": _function_inputs,
                                },
                            ),
                        ),
                    ),
                },
            ),
        },
    ),
    "FunctionTest": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"FunctionTest:{value}:def",
                                type="function",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                local_key_fn=lambda value: "spec",
                sub_structure={
                    "functionRef": _function_ref,
                    "currentResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "current_resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "current_value",
                        ),
                    ),
                    "inputs": _function_inputs,
                    "expectedResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "expected_value",
                        ),
                    ),
                    "expectedOkValue": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_ok_value",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "expected_value",
                        ),
                    ),
                },
            ),
        },
    ),
    "ResourceTemplate": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                index_key_fn=lambda value: f"ResourceTemplate:{value}:def",
                                type="function",
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
            "spec": SemanticStructure(
                sub_structure={
                    "behavior": _behavior,
                    "managedResource": _managed_resource,
                    "template": SemanticStructure(type="property"),
                },
            ),
        },
    ),
    ALL: SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure=SemanticStructure(
                    sub_structure={
                        "name": SemanticStructure(
                            sub_structure=SemanticStructure(
                                modifier=[Modifier.definition],
                            ),
                        ),
                        "namespace": _namespace,
                    },
                ),
            ),
        },
    ),
}
