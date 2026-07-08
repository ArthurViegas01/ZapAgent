/**
 * Symmetric encryption for integration secrets at rest (ZAP-006).
 *
 * Format: base64(iv[12] | ciphertext | tag[16]), AES-256-GCM. This is the
 * exact same layout the Python API produces (cryptography's AESGCM appends the
 * tag to the ciphertext), so a secret written by either runtime is readable by
 * the other. The key is derived as SHA-256(APP_ENCRYPTION_KEY) on both sides.
 */
import { createCipheriv, createDecipheriv, createHash, randomBytes } from "node:crypto";

function loadKey(): Buffer {
  const raw = process.env.APP_ENCRYPTION_KEY ?? "";
  if (!raw) throw new Error("APP_ENCRYPTION_KEY is not configured");
  return createHash("sha256").update(raw).digest(); // 32 bytes
}

export function encryptionConfigured(): boolean {
  return Boolean(process.env.APP_ENCRYPTION_KEY);
}

export function encryptSecret(plaintext: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", loadKey(), iv);
  const enc = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, enc, tag]).toString("base64");
}

export function decryptSecret(blob: string): string {
  const data = Buffer.from(blob, "base64");
  const iv = data.subarray(0, 12);
  const tag = data.subarray(data.length - 16);
  const ct = data.subarray(12, data.length - 16);
  const decipher = createDecipheriv("aes-256-gcm", loadKey(), iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]).toString("utf8");
}
