from __future__ import annotations


from .semantics import Modifier, SemanticStructure


ALL = "*"


def step_path_indexer(value) -> str:
    try:
        return (
            f"Step:{''.join(name.value for key, name in value if key.value == 'label')}"
        )
    except Exception as err:
        raise Exception(f"Failed to process '{value}', with {err}")


def function_ref_indexer(value) -> tuple[str, str] | None:
    try:
        kind = None
        name = None
        for key, key_value in value:
            if key.value == "kind":
                kind = key_value.value

            if key.value == "name":
                name = key_value.value

        if not (kind and name):
            return None

        return ("name", f"{kind}:{name}:ref")

    except Exception as err:
        raise Exception(f"Failed to process '{value}', with {err}")


_api_version: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: f"api_version",
        type="namespace",
    )
)

_kind: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: f"kind",
        type="type",
    ),
)

_namespace: SemanticStructure = SemanticStructure(
    sub_structure=SemanticStructure(
        type="namespace",
    ),
)

_logic_ref: SemanticStructure = SemanticStructure(
    type="property",
    sub_structure=SemanticStructure(
        strict_sub_structure_keys=True,
        field_index_key_fn=function_ref_indexer,
        sub_structure={
            "kind": SemanticStructure(
                type="property",
                sub_structure=SemanticStructure(type="type"),
            ),
            "name": SemanticStructure(
                type="property",
                sub_structure=SemanticStructure(
                    type="function",
                ),
            ),
        },
    ),
)

_api_config: SemanticStructure = SemanticStructure(
    type="property",
    strict_sub_structure_keys=True,
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
        "owned": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="number"),
        ),
        "deleteIfExists": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="number"),
        ),
        "readonly": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="number"),
        ),
        "name": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="string"),
        ),
        "namespace": SemanticStructure(
            type="parameter",
            sub_structure=SemanticStructure(type="string"),
        ),
    },
)

_function_inputs: SemanticStructure = SemanticStructure(
    type="property",
    local_key_fn=lambda value: "inputs",
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: "input-values",
        sub_structure={
            ALL: SemanticStructure(
                local_key_fn=lambda value: f"input:{value}", type="variable"
            )
        },
    ),
)

_function_input_overrides: SemanticStructure = SemanticStructure(
    type="property",
    local_key_fn=lambda value: "input_overrides",
    sub_structure=SemanticStructure(
        local_key_fn=lambda value: "input-values",
        sub_structure={
            ALL: SemanticStructure(
                local_key_fn=lambda value: f"input:{value}", type="variable"
            )
        },
    ),
)


_validators = SemanticStructure(
    type="property",
    strict_sub_structure_keys=True,
    sub_structure={
        "assert": SemanticStructure(
            type="property",
            sub_structure=SemanticStructure(type="string"),
        ),
        "ok": SemanticStructure(
            type="property", strict_sub_structure_keys=True, sub_structure={}
        ),
        "skip": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
        "depSkip": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
        "retry": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
                "delay": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="number"),
                ),
            },
        ),
        "permFail": SemanticStructure(
            type="property",
            strict_sub_structure_keys=True,
            sub_structure={
                "message": SemanticStructure(
                    type="property",
                    sub_structure=SemanticStructure(type="string"),
                ),
            },
        ),
    },
)

SEMANTIC_TYPE_STRUCTURE: dict[str, SemanticStructure] = {
    "ResourceFunction": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure={
                    "name": SemanticStructure(
                        sub_structure=SemanticStructure(
                            index_key_fn=lambda value: f"ResourceFunction:{value}:def",
                            type="function",
                            modifier=[Modifier.definition],
                        ),
                    ),
                    "namespace": _namespace,
                },
            ),
            "spec": SemanticStructure(
                strict_sub_structure_keys=True,
                sub_structure={
                    "preconditions": _validators,
                    "locals": SemanticStructure(
                        type="property",
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                type="property",
                            ),
                        ),
                    ),
                    "apiConfig": _api_config,
                    "resourceTemplateRef": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "name": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(
                                    type="string",
                                    index_key_fn=lambda value: (
                                        None
                                        if value.startswith("=")
                                        else f"ResourceTemplate:{value}:ref"
                                    ),
                                ),
                            ),
                        },
                    ),
                    "resource": SemanticStructure(
                        type="property",
                    ),
                    "overlays": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure=SemanticStructure(
                            type="property",
                            strict_sub_structure_keys=True,
                            sub_structure={
                                "skipIf": SemanticStructure(
                                    type="property",
                                ),
                                "overlay": SemanticStructure(
                                    type="property",
                                ),
                                "overlayRef": _logic_ref,
                                "inputs": _function_inputs,
                            },
                        ),
                    ),
                    "create": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "enabled": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="number"),
                            ),
                            "delay": SemanticStructure(
                                type="parameter",
                                sub_structure=SemanticStructure(type="number"),
                            ),
                            "overlay": SemanticStructure(
                                type="property",
                            ),
                        },
                    ),
                    "update": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "patch": SemanticStructure(
                                type="parameter",
                                strict_sub_structure_keys=True,
                                sub_structure={
                                    "delay": SemanticStructure(type="number")
                                },
                            ),
                            "recreate": SemanticStructure(
                                type="parameter",
                                strict_sub_structure_keys=True,
                                sub_structure={
                                    "delay": SemanticStructure(type="number")
                                },
                            ),
                            "never": SemanticStructure(
                                type="parameter",
                                strict_sub_structure_keys=True,
                                sub_structure={},
                            ),
                        },
                    ),
                    "delete": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "abandon": SemanticStructure(
                                type="parameter",
                                strict_sub_structure_keys=True,
                                sub_structure={},
                            ),
                            "destroy": SemanticStructure(
                                type="parameter",
                                strict_sub_structure_keys=True,
                                sub_structure={},
                            ),
                        },
                    ),
                    "postconditions": _validators,
                    "return": SemanticStructure(
                        type="property",
                    ),
                },
            ),
        },
    ),
    "ValueFunction": SemanticStructure(
        sub_structure={
            "apiVersion": _api_version,
            "kind": _kind,
            "metadata": SemanticStructure(
                sub_structure={
                    "name": SemanticStructure(
                        sub_structure=SemanticStructure(
                            index_key_fn=lambda value: f"ValueFunction:{value}:def",
                            type="function",
                            modifier=[Modifier.definition],
                        ),
                    ),
                    "namespace": _namespace,
                },
            ),
            "spec": SemanticStructure(
                strict_sub_structure_keys=True,
                sub_structure={
                    "preconditions": _validators,
                    "locals": SemanticStructure(
                        type="property",
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                type="property",
                            ),
                        ),
                    ),
                    "return": SemanticStructure(
                        type="property",
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                type="property",
                            ),
                        ),
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
                strict_sub_structure_keys=True,
                sub_structure={
                    "crdRef": SemanticStructure(
                        type="typeParameter",
                        strict_sub_structure_keys=True,
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
                                strict_sub_structure_keys=True,
                                sub_structure={
                                    "label": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: f"label:{value}",
                                            type="event",
                                            modifier=[Modifier.definition],
                                        ),
                                    ),
                                    "ref": _logic_ref,
                                    "refSwitch": SemanticStructure(
                                        type="property",
                                        strict_sub_structure_keys=True,
                                        sub_structure=SemanticStructure(
                                            type="property",
                                            strict_sub_structure_keys=True,
                                            sub_structure={
                                                "switchOn": SemanticStructure(
                                                    type="property"
                                                ),
                                                "cases": SemanticStructure(
                                                    type="property",
                                                    sub_structure=SemanticStructure(
                                                        strict_sub_structure_keys=True,
                                                        sub_structure=SemanticStructure(
                                                            strict_sub_structure_keys=True,
                                                            field_index_key_fn=function_ref_indexer,
                                                            sub_structure={
                                                                "case": SemanticStructure(
                                                                    type="property",
                                                                    sub_structure=SemanticStructure(
                                                                        type="string"
                                                                    ),
                                                                ),
                                                                "default": SemanticStructure(
                                                                    type="property",
                                                                    sub_structure=SemanticStructure(
                                                                        type="number"
                                                                    ),
                                                                ),
                                                                "kind": SemanticStructure(
                                                                    type="property",
                                                                    sub_structure=SemanticStructure(
                                                                        type="type"
                                                                    ),
                                                                ),
                                                                "name": SemanticStructure(
                                                                    type="property",
                                                                    sub_structure=SemanticStructure(
                                                                        type="function",
                                                                    ),
                                                                ),
                                                            },
                                                        ),
                                                    ),
                                                ),
                                            },
                                        ),
                                    ),
                                    "inputs": _function_inputs,
                                    "skipIf": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(
                                            type="string",
                                        ),
                                    ),
                                    "forEach": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "for_each",
                                        sub_structure={
                                            "itemIn": SemanticStructure(
                                                type="argument",
                                            ),
                                            "inputKey": SemanticStructure(
                                                type="argument",
                                                sub_structure=SemanticStructure(
                                                    type="parameter",
                                                    local_key_fn=lambda value: f"input:{value}",
                                                ),
                                            ),
                                            "state": SemanticStructure(type="property"),
                                            "condition": SemanticStructure(
                                                type="property",
                                                strict_sub_structure_keys=True,
                                                sub_structure={
                                                    "type": SemanticStructure(
                                                        type="property",
                                                        sub_structure=SemanticStructure(
                                                            type="type",
                                                        ),
                                                    ),
                                                    "name": SemanticStructure(
                                                        type="property",
                                                    ),
                                                },
                                            ),
                                        },
                                    ),
                                    "condition": SemanticStructure(
                                        type="property",
                                        strict_sub_structure_keys=True,
                                        sub_structure={
                                            "type": SemanticStructure(
                                                type="property",
                                                sub_structure=SemanticStructure(
                                                    type="type",
                                                ),
                                            ),
                                            "name": SemanticStructure(
                                                type="property",
                                            ),
                                        },
                                    ),
                                    "state": SemanticStructure(type="property"),
                                },
                            ),
                        ),
                    ),
                    "status": SemanticStructure(
                        type="property",
                        strict_sub_structure_keys=True,
                        sub_structure={
                            "conditions": SemanticStructure(
                                type="property",
                                sub_structure=SemanticStructure(
                                    strict_sub_structure_keys=True,
                                    sub_structure={
                                        "type": SemanticStructure(
                                            type="property",
                                            sub_structure=SemanticStructure(
                                                type="type"
                                            ),
                                        ),
                                        "name": SemanticStructure(type="property"),
                                        "step": SemanticStructure(type="property"),
                                    },
                                ),
                            ),
                            "state": SemanticStructure(type="property"),
                        },
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
                strict_sub_structure_keys=True,
                sub_structure={
                    "functionRef": _logic_ref,
                    "currentResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "current-resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "current-value",
                        ),
                    ),
                    "inputs": _function_inputs,
                    "testCases": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "test-cases",
                        sub_structure=SemanticStructure(
                            sub_structure=SemanticStructure(
                                type="property",
                                local_key_fn=lambda value: "test-case-body",
                                sub_structure={
                                    "label": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "label",
                                        sub_structure=SemanticStructure(type="string"),
                                    ),
                                    "variant": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(type="number"),
                                    ),
                                    "skip": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(type="number"),
                                    ),
                                    "currentResource": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "current-resource",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: "current-resource-value",
                                        ),
                                    ),
                                    "overlayResource": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "overlay-resource",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: "overlay-resource-value",
                                        ),
                                    ),
                                    "inputOverrides": _function_input_overrides,
                                    "expectResource": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "expected-resource",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: "expected-value",
                                        ),
                                    ),
                                    "expectOutcome": _validators,
                                    "expectReturn": SemanticStructure(
                                        type="property",
                                        local_key_fn=lambda value: "expected-return",
                                        sub_structure=SemanticStructure(
                                            local_key_fn=lambda value: "expected-value",
                                        ),
                                    ),
                                    "expectDelete": SemanticStructure(
                                        type="property",
                                        sub_structure=SemanticStructure(
                                            type="number",
                                        ),
                                    ),
                                },
                            ),
                        ),
                    ),
                    "expectResource": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_resource",
                        sub_structure=SemanticStructure(
                            local_key_fn=lambda value: "expected_value",
                        ),
                    ),
                    "expectOutcome": _validators,
                    "expectReturn": SemanticStructure(
                        type="property",
                        local_key_fn=lambda value: "expected_return",
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
                strict_sub_structure_keys=True,
                sub_structure={
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
