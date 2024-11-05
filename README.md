# koreo-tooling

Developer tooling to make working with Koreo Workflows, Functions, and
ResourceTemplates easy.

We provide a CLI tool, for use within CICD or by hand.

More helpfully, we provide a language server that surfaces issues within your
IDE.


## CLI

    pdm run python src/koreo-cli.py --yaml-dir=<your-koreo-yamls> --check


## LSP

Register the Koreo LSP with your IDE. Maybe in a config block like this:

    "koreo-ls": {
      "command": "koreo-ls",
      "filetypes": ["koreo"],
      "rootPatterns": ["*.koreo"]
    }
