# koreo-tooling

Developer tooling to make working with Koreo Workflows, Functions, and
ResourceTemplates easy.

We provide a CLI tool, for use within CICD or by hand.

More helpfully, we provide a language server that surfaces issues within your
IDE.


## Inspector

A helper to get information about Workflow trigger resource, and the resources
created by a Workflow. Without `-v`, basic summary information will be printed
for each resource. With each additional `-v`, more information is output (up to
the full object).

    pdm run python src/inspector.py TriggerDummy -n koreo-update-loop difference-demo -v



## Language Server

Register the Koreo LSP with your IDE. Maybe in a config block like this:

    "koreo-ls": {
      "command": "koreo-ls",
      "filetypes": ["koreo"],
      "root_dir": ["*.git"]
    }

## Implemented Capabilities

### Diagnostics

Robust diagnostic messages to help spot errors early, ensure tests are passing,
and that resources are correctly named.

Diagnostics combined with FunctionTests provide an immediate and rich
development feedback loop to make writing Koreo feel like a first-class
language.

### Semantic Syntax Highlighting

We support LSP semantic syntax highlighting capabilities. This provides rich
syntax highlighting with deeper information than typically available.

### Go to Def / Ref

Go to Workflow or Function definitions or list references. Navigation supports
constant named ResourceTemplates as well.

### Hover Status for Workflows & Functions

Hover information is available for Workflows, Workflow Steps, and Functions.

This is an area with a lot of potential for enhancement going forward.


### Inlay Hints to indicate FunctionTest outcome

To make testing within Koreo easy, FunctionTest supports inlay-hints to
indicate success or failure of the function test.


### Basic completion (Early WIP)

Context-aware auto-completion recommendations. Recommending implemented
function names for Workflow steps, for example.


