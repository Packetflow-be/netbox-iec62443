# Contributing

Thank you for helping. Before you start on something larger than a small fix, open an
[issue](https://github.com/Packetflow-be/netbox-iec62443/issues) or a
[discussion](https://github.com/Packetflow-be/netbox-iec62443/discussions) so we can agree on the approach.

- **Bugs**: open an issue with the NetBox and plugin versions, what you did, what you expected and what
  happened. A traceback or the failing API request helps.
- **Features**: describe the problem first (what you need to record or see, and for whom), then the solution
  you have in mind. IEC 62443 terms are welcome; the plugin cannot include the standard's copyrighted texts.
- **Pull requests**: one change per pull request, with tests. Run `ruff check .` and the test suite (see
  [docs/development.md](docs/development.md)), and add a line to the *Unreleased* section of
  [CHANGELOG.md](CHANGELOG.md). A new migration must depend only on NetBox 4.7.0 migrations.
- **Translations**: see [docs/development.md](docs/development.md#translations).

By contributing you agree that your contribution is licensed under the Apache License 2.0.
