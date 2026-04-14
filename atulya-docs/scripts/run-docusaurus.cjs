#!/usr/bin/env node

const {spawnSync} = require('node:child_process');
const path = require('node:path');

const args = process.argv.slice(2);
if (args.length === 0) {
  console.error('Usage: node scripts/run-docusaurus.cjs <command> [...args]');
  process.exit(1);
}

const env = {...process.env};

// Some shells export DEBUG=release (or similar), which Docusaurus/webpack can
// inline into server bundles in a broken way during SSG. Keep docs commands
// deterministic by clearing it at the process boundary.
delete env.DEBUG;

const siteRoot = path.resolve(__dirname, '..');
const docusaurusPackage = require.resolve('@docusaurus/core/package.json', {
  paths: [siteRoot],
});
const cliEntry = path.join(path.dirname(docusaurusPackage), 'bin', 'docusaurus.mjs');

const result = spawnSync(process.execPath, [cliEntry, ...args], {
  stdio: 'inherit',
  env,
  cwd: siteRoot,
});

if (result.error) {
  console.error(result.error);
  process.exit(1);
}

process.exit(result.status ?? 0);
