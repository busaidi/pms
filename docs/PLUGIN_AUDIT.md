# OpenKos plugin migration audit

Audit date: 29 September 2026.

The Laravel command `php artisan plugin:list` reports: `No runtime plugins are
installed.` No production plugin package therefore requires a Django port for
cutover. Composer dependencies remain framework/application dependencies and
are not runtime OpenKos plugins.

The Django replacement exposes ordered registries for navigation, dashboards,
workspaces, settings, permissions, notification drivers, payment gateways,
routes, migrations, and event listeners. Extensions declare version and
dependency requirements through an `ExtensionManifest` discovered from an
installed Django app's `pms_extension` module. A built-in reference extension
exercises every lifecycle point and is kept as a system extension.

PHP/Composer plugin archives cannot execute in the Python process. Any plugin
installed later must be reimplemented as an installed Django app using this
contract and pass its own migration, authorization, health, and failure tests.
