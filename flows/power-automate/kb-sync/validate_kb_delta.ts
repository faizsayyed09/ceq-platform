interface KbAction {
  action: string;
  client_key?: string;
  old_client_key?: string;
  was_retired?: boolean;
}

interface KbShard {
  shard_id: string;
  client_keys?: string[];
  aliases?: string[];
  folder_id: number | null;
  mission_id: number | null;
  active: boolean;
  article_count: number;
  cap: number;
  fallback?: boolean;
}

function main(workbook: ExcelScript.Workbook, clientMapJson: string, actionsJson: string) {
  const map = JSON.parse(clientMapJson) as {
    default_shard: string;
    refuse_upload_at: number;
    shards: KbShard[];
  };
  const actions = JSON.parse(actionsJson) as KbAction[];
  const planned: Array<{ action: string; shard_id: string; old_shard_id: string | null; folder_id: number | null }> = [];
  const errors: string[] = [];

  for (const action of actions) {
    const kind = String(action.action || "").toLowerCase();
    if (!["upload", "replace", "delete"].includes(kind)) {
      errors.push("Unknown delta action");
      continue;
    }
    const newShard = resolveShard(action.client_key || "", map);
    const oldShard = action.old_client_key ? resolveShard(action.old_client_key, map) : null;
    if (kind !== "delete" && newShard == null) {
      errors.push("Unmapped client");
      continue;
    }
    if (oldShard == null && action.old_client_key) {
      errors.push("Unmapped old client");
      continue;
    }
    if (kind === "upload") {
      const limit = map.refuse_upload_at || 195;
      if ((newShard?.article_count || 0) >= limit) {
        errors.push("Shard refuses upload at configured capacity");
        continue;
      }
    }
    planned.push({
      action: kind === "upload" && action.was_retired ? "upload" : kind,
      shard_id: newShard?.shard_id || "",
      old_shard_id: oldShard?.shard_id || null,
      folder_id: newShard?.folder_id || null
    });
  }
  return JSON.stringify({ ok: errors.length === 0, planned: planned, errors: errors });
}

function normalizeClient(value: string): string {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
}

function resolveShard(client: string, map: { default_shard: string; shards: KbShard[] }): KbShard | null {
  const normalized = normalizeClient(client);
  for (const shard of map.shards) {
    const keys = (shard.client_keys || []).map(normalizeClient);
    const aliases = (shard.aliases || []).map(normalizeClient);
    if (keys.includes(normalized) || aliases.includes(normalized)) {
      return shard;
    }
  }
  return map.shards.find((shard) => shard.shard_id === map.default_shard) || null;
}
