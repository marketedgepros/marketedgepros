import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const frontendDirectory = path.resolve(testDirectory, '..');
const appPath = path.join(frontendDirectory, 'src', 'App.jsx');
const appSource = fs.readFileSync(appPath, 'utf8');

function resolveModule(fromPath, specifier) {
  const candidate = path.resolve(path.dirname(fromPath), specifier);
  const candidates = [
    candidate,
    `${candidate}.js`,
    `${candidate}.jsx`,
    path.join(candidate, 'index.js'),
    path.join(candidate, 'index.jsx'),
  ];

  return candidates.find((filePath) => fs.existsSync(filePath));
}

test('App lazy-route component inventory resolves to tracked source modules', () => {
  const imports = [...appSource.matchAll(/const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(['"]([^'"]+)['"]\)\)/g)];

  assert.ok(imports.length > 0, 'App must declare lazy route components');
  for (const [, componentName, specifier] of imports) {
    assert.ok(
      resolveModule(appPath, specifier),
      `${componentName} must resolve from ${specifier}`,
    );
  }
});

test('affiliate management routes use canonical agent pages and keep their role guards', () => {
  for (const componentName of ['TradersManagement', 'Commissions', 'Reports']) {
    assert.match(
      appSource,
      new RegExp(`const\\s+${componentName}\\s*=\\s*lazy\\(\\(\\)\\s*=>\\s*import\\(['"]\\.\\/pages\\/agent\\/${componentName}['"]\\)\\)`),
    );
  }
  assert.match(
    appSource,
    /path="\/affiliate\/traders"[\s\S]{0,500}allowedRoles=\{\['affiliate'\]\}/,
  );
  for (const componentName of ['TradersManagement', 'Commissions', 'Reports']) {
    assert.match(
      fs.readFileSync(path.join(frontendDirectory, 'src', 'pages', 'agent', `${componentName}.jsx`), 'utf8'),
      new RegExp(`export default function ${componentName}\\(\\)`),
    );
  }
});

test('frontend build script remains a Vite production build smoke command', () => {
  const packageJson = JSON.parse(fs.readFileSync(path.join(frontendDirectory, 'package.json'), 'utf8'));
  assert.equal(packageJson.scripts.build, 'vite build');
});
