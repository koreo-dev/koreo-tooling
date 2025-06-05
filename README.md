# Koreo Tooling

Developer tooling to make working with Koreo Workflows, Functions, and ResourceTemplates easy. This package provides both a CLI tool for automation and CI/CD, and a language server that integrates with IDEs to provide real-time feedback and enhanced development experience.

## Overview

Koreo is a Kubernetes-native workflow engine that uses CEL (Common Expression Language) expressions embedded in YAML to define infrastructure automation. This tooling package provides:

- **CLI tools** for inspecting, applying, and managing Koreo resources
- **Language Server Protocol (LSP)** implementation for IDE integration
- **Syntax highlighting** with semantic understanding of CEL expressions
- **Diagnostics and validation** for Koreo resources
- **Code completion** and intelligent suggestions

## Installation

```bash
# Install with PDM
pdm install

# Or install in development mode
pdm install -G dev
```

## CLI Usage

### Commands

#### `koreo` - Main CLI tool

```bash
# Apply Koreo resources to cluster
koreo apply <file_or_directory>

# Inspect resources and their relationships  
koreo inspect <resource_type> -n <namespace> <name> [-v]

# Prune unused or orphaned resources
koreo prune [options]
```

#### Examples

```bash
# Apply all YAML files in a directory
koreo apply ./workflows/

# Inspect a workflow with verbose output
koreo inspect Workflow -n default my-workflow -vv

# Get detailed information about resource relationships
koreo inspect TriggerDummy -n koreo-update-loop difference-demo -v
```

### Inspector Tool

The inspector helps you understand resource relationships and troubleshoot issues:

- **Basic mode**: Shows summary information
- **Verbose (`-v`)**: Shows detailed resource information  
- **Very verbose (`-vv`)**: Shows full object details
- **Extremely verbose (`-vvv`)**: Shows all related resources

## Language Server

### Setup

Register the Koreo LSP with your IDE. Example configuration for various editors:

#### VS Code (settings.json)
```json
{
  "koreo-ls.command": "koreo-ls",
  "koreo-ls.filetypes": ["yaml"],
  "koreo-ls.rootDir": [".git"]
}
```

#### Neovim (lua config)
```lua
require('lspconfig').koreo_ls.setup({
  cmd = { "koreo-ls" },
  filetypes = { "yaml", "koreo" },
  root_dir = require('lspconfig').util.root_pattern(".git"),
})
```

### Language Server Capabilities

#### 🔍 **Diagnostics**
- Real-time validation of Koreo resources
- CEL expression syntax checking
- Function test result integration
- Resource reference validation
- Schema compliance checking

#### 🎨 **Semantic Syntax Highlighting**
- Rich syntax highlighting for CEL expressions
- Distinguished highlighting for:
  - Keywords (`true`, `false`, `null`, `in`)
  - Functions (`size()`, `has()`, `map()`, `filter()`)
  - Numbers (integers, floats, scientific notation)
  - Strings and operators
  - Variables and step references

#### 🧭 **Navigation**
- **Go to Definition**: Jump to function and workflow definitions
- **Find References**: List all references to a resource
- **Hover Information**: Rich tooltips with resource status and documentation

#### ✨ **Code Completion**
- Context-aware suggestions based on cursor position
- CEL function signatures with parameter hints
- Resource name completion from cache
- Workflow step reference completion
- Common Koreo patterns as snippets

#### 💡 **Inlay Hints**
- Function test success/failure indicators
- Parameter type hints for complex expressions
- Resource status indicators

## Architecture

### Core Components

#### 1. **Indexing System** (`src/koreo_tooling/indexing/`)

The indexing system provides semantic analysis of Koreo YAML files:

- **`cel_semantics.py`**: Lexer and parser for CEL expressions
  - Tokenizes CEL syntax (operators, keywords, functions)
  - Generates semantic nodes for syntax highlighting
  - Handles string escaping and number parsing

- **`koreo_semantics.py`**: Schema definitions for Koreo resources
  - Defines semantic structure for ValueFunction, ResourceFunction, Workflow, etc.
  - Maps YAML structure to semantic types
  - Handles cross-references between resources

- **`extractor.py`**: Extracts semantic information from YAML nodes
  - Detects CEL expressions (lines starting with `=`)
  - Integrates YAML parsing with CEL analysis
  - Generates semantic anchors for navigation

#### 2. **Language Server** (`src/koreo_tooling/langserver/`)

Implements the Language Server Protocol for IDE integration:

- **`fileprocessor.py`**: Main file analysis engine
  - Processes YAML files and extracts semantic tokens
  - Generates diagnostics for errors and warnings
  - Manages semantic range indexes for navigation

- **`completions.py`**: Context-aware code completion
  - CEL function completion with signatures
  - Resource reference completion
  - Pattern-based suggestions for common structures

- **`hover.py`**: Hover information provider
  - Shows resource status and documentation
  - Displays function test results
  - Provides workflow step information

- **`codelens.py`**: Code lens actions
  - Quick fix suggestions for test mismatches
  - Resource status indicators
  - Automated corrections for common issues

#### 3. **CLI Tools** (`src/cli/`)

Command-line interface for resource management:

- **`apply.py`**: Resource application and deployment
- **`inspect.py`**: Resource inspection and relationship analysis
- **`prune.py`**: Cleanup of unused resources

#### 4. **Function Testing** (`src/koreo_tooling/function_test.py`)

Integrated testing framework for Koreo functions:

- Executes function tests and captures results
- Compares expected vs actual outputs
- Generates detailed mismatch reports
- Integrates with language server for real-time feedback

### CEL Expression Support

The tooling provides comprehensive support for CEL (Common Expression Language):

#### Supported Features:
- **Numbers**: Integers, floats, scientific notation (`1.23e-4`)
- **Strings**: Single/double quotes with escape sequences
- **Operators**: Arithmetic (`+`, `-`, `*`, `/`, `%`), comparison, logical
- **Functions**: `size()`, `has()`, `map()`, `filter()`, `matches()`, etc.
- **Variables**: `inputs`, `parent`, `self`, step references (`${step_name}`)
- **Collections**: Arrays, objects with proper indexing

#### Expression Detection:
```yaml
# CEL expressions are detected by the '=' prefix
spec:
  return:
    result: =inputs.value * 2 + 3.14159
    active_items: =inputs.items.filter(i, i.active == true)
    formatted_name: =inputs.name.startsWith("test-") ? inputs.name : "test-" + inputs.name
```

### Resource Types

The tooling supports all Koreo resource types:

#### **ValueFunction**
Pure functions that transform inputs to outputs:
```yaml
apiVersion: koreo.dev/v1beta1
kind: ValueFunction
metadata:
  name: calculate-metrics
spec:
  return:
    total: =inputs.values.map(v, v.amount).sum()
    average: =inputs.values.map(v, v.amount).sum() / size(inputs.values)
```

#### **ResourceFunction**  
Functions that manage Kubernetes resources:
```yaml
apiVersion: koreo.dev/v1beta1
kind: ResourceFunction
metadata:
  name: deploy-app
spec:
  apiConfig:
    apiVersion: apps/v1
    kind: Deployment
  resource:
    metadata:
      name: =inputs.app_name + "-deployment"
    spec:
      replicas: =inputs.replicas
```

#### **Workflow**
Orchestrates multiple functions in steps:
```yaml
apiVersion: koreo.dev/v1beta1
kind: Workflow
metadata:
  name: ci-pipeline
spec:
  steps:
    - label: build
      ref:
        kind: ValueFunction
        name: build-image
      inputs:
        source: =inputs.repository
    
    - label: deploy
      ref:
        kind: ResourceFunction
        name: deploy-app
      inputs:
        image: =${build.image_url}
```

#### **FunctionTest**
Tests for validating function behavior:
```yaml
apiVersion: koreo.dev/v1beta1
kind: FunctionTest
metadata:
  name: test-calculate-metrics
spec:
  functionRef:
    kind: ValueFunction
    name: calculate-metrics
  testCases:
    - label: basic-calculation
      inputs:
        values: [{"amount": 10}, {"amount": 20}]
      expectReturn:
        total: 30
        average: 15
```

## Development

### Running Tests

```bash
# Run all tests
pdm run test

# Run tests with coverage
pdm run test-cov

# Run specific test file
pdm run pytest tests/koreo_tooling/indexing/test_cel_semantics.py
```

### Code Quality

```bash
# Check code style and issues
pdm run lint

# Auto-fix issues where possible  
pdm run lint-fix

# Format code
pdm run format
```

### Development Server

```bash
# Start the language server for testing
pdm run koreo-ls
```

## Contributing

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Make your changes** and add tests
4. **Run the test suite**: `pdm run test`
5. **Check code quality**: `pdm run lint`
6. **Commit your changes**: `git commit -m 'Add amazing feature'`
7. **Push to the branch**: `git push origin feature/amazing-feature`
8. **Open a Pull Request**

### Adding New Features

#### Language Server Features
- Add new completion providers in `src/koreo_tooling/langserver/completions.py`
- Extend diagnostics in `src/koreo_tooling/langserver/cel_diagnostics.py`
- Add hover information in `src/koreo_tooling/langserver/hover.py`

#### CEL Expression Support
- Extend the lexer in `src/koreo_tooling/indexing/cel_semantics.py`
- Add new semantic rules in `src/koreo_tooling/indexing/koreo_semantics.py`

#### CLI Commands
- Add new commands in `src/cli/`
- Update the main CLI entry point in `src/cli/__main__.py`

## License

Apache-2.0 - see [LICENSE](LICENSE) file for details.

## Links

- **Homepage**: https://koreo.dev
- **Documentation**: https://docs.koreo.dev
- **Issues**: https://github.com/koreo-dev/tooling/issues