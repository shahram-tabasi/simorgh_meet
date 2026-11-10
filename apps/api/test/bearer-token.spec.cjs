const test = require('node:test');
const assert = require('node:assert/strict');
const { extractBearerToken } = require('../dist/auth/bearer-token');

test('extracts a standard bearer token', () => {
  assert.equal(extractBearerToken('Bearer abc.def.ghi'), 'abc.def.ghi');
});

test('accepts case-insensitive bearer scheme', () => {
  assert.equal(extractBearerToken('bearer opaque-token'), 'opaque-token');
});

test('rejects missing, malformed, and ambiguous authorization headers', () => {
  assert.equal(extractBearerToken(undefined), null);
  assert.equal(extractBearerToken(''), null);
  assert.equal(extractBearerToken('Basic abc'), null);
  assert.equal(extractBearerToken('Bearer token with spaces'), null);
  assert.equal(extractBearerToken('Bearer  token'), null);
});
