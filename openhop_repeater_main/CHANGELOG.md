# Changelog

## 2.1.1

- Prepare plugin-manager startup for the upcoming upstream Dev-to-Main promotion; this update does not switch Main to the Dev image.
- Retain direct Repeater startup for older images without the supervisor, and preserve configuration paths, clean-restart protection, and signal forwarding.

## 2.1.0

### Upgrade notes

- Existing installations keep the same add-on slug, `/config` location, and persistent data path. Take a Home Assistant backup before upgrading as a normal precaution.
- Valid existing configuration values, custom keys, and non-empty credentials are preserved while newly introduced defaults from the upstream `:main` template are added.
- When new defaults must be merged, `config.yaml` is rewritten as normalized YAML. Values are preserved, but comments, blank lines, anchors, quoting, and custom formatting are not.
- An empty `repeater.security.jwt_secret` is replaced with a unique signing secret. Existing browser or JWT sessions may require signing in again.
- Existing admin and guest passwords are not changed. Installations still using `admin123` or `guest123` should replace them in `config.yaml`.
- Invalid YAML is never overwritten. The add-on stops with a clear error so the existing file can be corrected.
- `config.yaml` is secured as `0600`; Home Assistant Studio Code Server can continue editing it through `/addon_configs`.

### Changes

- Create new configurations atomically from the template included in the selected upstream `:main` image.
- Generate unique admin and guest passwords plus a unique JWT signing secret for new installations.
- Add cold-backup metadata, clean signal forwarding, child reaping, and rapid-restart protection.
- Add repository validation, lifecycle and configuration tests, shell checks, Python linting, and Docker build CI for both channels.
- Redesign the repository and channel READMEs with installation guidance, security notes, related projects, and verified `aarch64` and `amd64` architecture badges.
- Remove the experimental-stage label from the Home Assistant App Store listing.

## 2.0.1

- Track upstream `MAIN` commit `60357f5` from `openhop/openhop-repeater:main`
- Previous tracked commit: `e17d113`
- Upstream diff: https://github.com/openhop-dev/openhop_repeater/compare/e17d1137ab2d2d5b86d03c99523272289b7688aa...60357f580876ceab5b3808a7ed00f81ae235c003
- Included upstream commits:
  - `2d5353a` fix(companion): improve transmission handling in RepeaterHandler
  - `e20eaa7` feat: add LAFVIN UPS Module 3S sensor plugin (lafvin_ups_3s)
  - `ab55748` fix: prevent advert echos in the packet table
  - `dc317b6` Merge pull request #261 from CarlsonCustoms/feat/lafvin-ups-3s-sensor
  - `37ee0e8` Add more unit tests for handler helpers, identity manager, CLI, key generation, and main functionality
  - `7b86716` Add unit tests for HTTP server, main daemon, service utilities, SQLite handler, and update endpoints
  - `31edaa9` fix: update installation scripts to use the correct branch name
  - `9da8317` docker: install rrdtool for runtime python

## 2.0.0

- Breaking rebrand to openHop Repeater add-on identifiers.
- Rename the add-on folder, slug, Home Assistant config folder hint, runtime config path, persistent data path, and bundled example file to openHop names.
- Remove automatic migration from legacy add-on config subfolders; copy any existing config and identity files into the new openHop add-on config folder before starting this version.

## 1.0.7

- Rebrand the add-on to openHop Repeater in Home Assistant metadata, docs, and bundled assets.
- Update upstream repository links and sync automation to `openhop-dev/openhop_repeater`.

## 1.0.6

- Track upstream `MAIN` commit `e17d113` from `openhopdev/openhop-repeater:main`
- Previous tracked commit: `a36cb6a`
- Upstream diff: https://github.com/openhop-dev/openhop_repeater/compare/a36cb6af44ab63247dd6d0f414afc6e53de18012...e17d1137ab2d2d5b86d03c99523272289b7688aa
- Included upstream commits:
  - `18300cb` feat: add GPS diagnostics web UI
  - `9cd2de9` chore: move GPS diagnostics UI to frontend repo
  - `8ae1c0f` feat: sync system time from GPS
  - `53f6e8a` fix: Remove old letsmesh_handler.py file
  - `3a6da40` fix: Always parse additional brokers
  - `b3fdfee` fix: Handle TLS for all MQTT connections
  - `d4aecf7` fix: Stop warning spam if brokers are disabled
  - `bdb98f3` fix(docs): Updated example config with TLS information

## 1.0.5

- Add user-local Python site-packages directories to `PYTHONPATH` before startup

## 1.0.4

- Make startup config inspection resilient when the inline Python YAML import fails

## 1.0.3

- Handle rootless upstream image builds in the add-on Dockerfiles
- Run the add-on wrapper as root so startup can manage `/etc/openhop_repeater`

## 1.0.2

- Handle rootless upstream image builds in the add-on Dockerfiles
- Run the add-on wrapper as root so startup can manage `/etc/openhop_repeater`

## 1.0.1

- Enable host networking so companion nodes can bind dynamic host ports

## 1.0.0

- Initial release of the Home Assistant add-on repository
- Add separate `dev` and `main` channel add-ons with aligned behavior
- Prepare `openhop_repeater_main` to track upstream `openhopdev/openhop-repeater:main`
