import { describe, expect, test } from 'vitest';
import {
  READEST_NIGHTLY_UPDATER_FILE,
  READEST_UPDATER_FILE,
  READEST_UPDATER_PUBKEY,
} from '@/services/constants';

const SELFHOST_UPDATER_FILE =
  'https://github.com/luoji12103/readest-self-hosted/releases/latest/download/latest.json';
const SELFHOST_UPDATER_PUBKEY =
  'dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IERDMTFCNEI4QTZDQUI5MkEKUldRcXVjcW11TFFSM0JBMkhWcGV0aW8yUlNneERzNnJtaUZjY3ViYmtyYWZwaEx4UzBEdi9WM3kK';

describe('selfhost updater configuration', () => {
  test('routes stable and nightly-channel checks to the selfhost release manifest', () => {
    expect(READEST_UPDATER_FILE).toBe(SELFHOST_UPDATER_FILE);
    expect(READEST_NIGHTLY_UPDATER_FILE).toBe(SELFHOST_UPDATER_FILE);
  });

  test('uses the selfhost release verification key', () => {
    expect(READEST_UPDATER_PUBKEY).toBe(SELFHOST_UPDATER_PUBKEY);
  });
});
