from __future__ import annotations

from .semantics import Modifier, SemanticStructure


VALUE = "."
ALL = "*"


SEMANTIC_TYPE_STRUCTURE: dict[str, dict[str, SemanticStructure]] = {
    "Function": {
        "apiVersion": {
            "sub_structure": {
                VALUE: {
                    "type": "namespace",
                },
            },
        },
        "kind": {
            "sub_structure": {
                VALUE: {
                    "type": "type",
                },
            },
        },
        "metadata": {
            "sub_structure": {
                "name": {
                    "sub_structure": {
                        VALUE: {
                            "type": "function",
                            "modifier": [Modifier.definition],
                        },
                    },
                },
                "namespace": {
                    "sub_structure": {
                        VALUE: {
                            "type": "namespace",
                        },
                    },
                },
            },
        },
        "spec": {
            "sub_structure": {
                "staticResource": {
                    "sub_structure": {
                        "behavior": {
                            "sub_structure": {
                                "load": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                                "create": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "number"},
                                    },
                                },
                                "update": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                                "delete": {
                                    "type": "parameter",
                                    "sub_structure": {
                                        VALUE: {"type": "enumMember"},
                                    },
                                },
                            },
                        },
                    },
                },
                "inputValidators": {
                    "sub_structure": {
                        "type": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "class"},
                            },
                        },
                        "message": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                        "test": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                    },
                },
                "outcome": {
                    "sub_structure": {
                        "okValue": {
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
    "Workflow": {
        "apiVersion": {
            "sub_structure": {
                VALUE: {"type": "namespace"},
            },
        },
        "kind": {"sub_structure": {VALUE: {"type": "type"}}},
        "metadata": {
            "type": "keyword",
            "sub_structure": {
                "name": {
                    "type": "keyword",
                    "sub_structure": {
                        VALUE: {
                            "type": "class",
                            "modifier": [Modifier.definition],
                        },
                    },
                },
                "namespace": {
                    "type": "keyword",
                    "sub_structure": {
                        VALUE: {
                            "type": "namespace",
                        },
                    },
                },
            },
        },
        "spec": {
            "type": "keyword",
            "sub_structure": {
                "crdRef": {
                    "type": "typeParameter",
                    "sub_structure": {
                        "apiGroup": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "namespace"},
                            },
                        },
                        "version": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "string"},
                            },
                        },
                        "kind": {
                            "type": "parameter",
                            "sub_structure": {
                                VALUE: {"type": "class"},
                            },
                        },
                    },
                },
                "steps": {
                    "type": "keyword",
                    "sub_structure": {
                        "label": {
                            "type": "property",
                            "sub_structure": {
                                VALUE: {
                                    "type": "event",
                                    "modifier": [Modifier.definition],
                                },
                            },
                        },
                        "functionRef": {
                            "type": "property",
                            "sub_structure": {
                                "name": {
                                    "type": "property",
                                    "sub_structure": {
                                        VALUE: {"type": "function"},
                                    },
                                },
                            },
                        },
                        "inputs": {
                            "type": "property",
                            "sub_structure": {
                                ALL: {
                                    "type": "variable",
                                    "sub_structure": {
                                        VALUE: {"type": "argument"},
                                    },
                                }
                            },
                        },
                    },
                },
            },
        },
    },
    ALL: {
        "apiVersion": {
            "sub_structure": {
                VALUE: {
                    "type": "namespace",
                },
            },
        },
        "kind": {
            "sub_structure": {
                VALUE: {
                    "type": "type",
                },
            },
        },
        "metadata": {
            "sub_structure": {
                "name": {
                    "sub_structure": {
                        VALUE: {
                            "modifier": [Modifier.definition],
                        },
                    },
                },
                "namespace": {
                    "sub_structure": {
                        VALUE: {
                            "type": "namespace",
                        },
                    },
                },
            },
        },
        ALL: {
            "type": "keyword",
        },
    },
}
