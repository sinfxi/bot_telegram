export interface BotState {
  [key: string]: unknown;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface CommunityMessage {
  chat_id: number;
  message_id: number;
  sender_id?: number | null;
  sender_name?: string;
  username?: string | null;
  text?: string;
  media_type?: string;
  is_bot?: boolean;
  date?: string | null;
}

export class FxiD1Store {
  constructor(private readonly db: D1Database) {}

  async loadBotState<T extends BotState = BotState>(defaults: T): Promise<T> {
    const row = await this.db.prepare(
      "SELECT data FROM fxi_bot_state WHERE id = 1",
    ).first<{ data: string }>();
    if (!row?.data) return structuredClone(defaults);
    const parsed = JSON.parse(row.data) as Partial<T>;
    return { ...structuredClone(defaults), ...parsed };
  }

  async saveBotState(state: BotState): Promise<void> {
    await this.db.prepare(
      `INSERT INTO fxi_bot_state (id, data, updated_at)
       VALUES (1, ?, CURRENT_TIMESTAMP)
       ON CONFLICT(id) DO UPDATE SET data = excluded.data, updated_at = CURRENT_TIMESTAMP`,
    ).bind(JSON.stringify(state)).run();
  }

  async loadChatHistory(userId: number, providerId: string, limit = 30): Promise<ChatMessage[]> {
    const safeLimit = Math.max(1, Math.min(100, Math.trunc(limit)));
    const result = await this.db.prepare(
      `SELECT role, content FROM (
         SELECT id, role, content FROM fxi_chat_messages
         WHERE user_id = ? AND provider_id = ? ORDER BY id DESC LIMIT ?
       ) recent ORDER BY id ASC`,
    ).bind(userId, providerId, safeLimit).all<ChatMessage>();
    return result.results ?? [];
  }

  async saveChatTurn(userId: number, providerId: string, userText: string, assistantText: string): Promise<void> {
    await this.db.batch([
      this.db.prepare(
        "INSERT INTO fxi_chat_messages (user_id, provider_id, role, content) VALUES (?, ?, 'user', ?)",
      ).bind(userId, providerId, userText.slice(0, 12000)),
      this.db.prepare(
        "INSERT INTO fxi_chat_messages (user_id, provider_id, role, content) VALUES (?, ?, 'assistant', ?)",
      ).bind(userId, providerId, assistantText.slice(0, 12000)),
    ]);
  }

  async clearChatHistory(userId: number, providerId: string): Promise<void> {
    await this.db.prepare(
      "DELETE FROM fxi_chat_messages WHERE user_id = ? AND provider_id = ?",
    ).bind(userId, providerId).run();
  }

  async saveCommunityMessage(message: CommunityMessage): Promise<void> {
    if (!Number.isSafeInteger(message.chat_id) || !Number.isSafeInteger(message.message_id) || message.message_id <= 0) {
      throw new Error("invalid_chat_or_message_id");
    }
    await this.db.prepare(
      `INSERT INTO fxi_community_messages
       (chat_id, message_id, sender_id, sender_name, username, body, media_type, is_bot, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
       ON CONFLICT(chat_id, message_id) DO UPDATE SET
         sender_id=excluded.sender_id, sender_name=excluded.sender_name,
         username=excluded.username, body=excluded.body, media_type=excluded.media_type,
         is_bot=excluded.is_bot, created_at=excluded.created_at`,
    ).bind(
      message.chat_id, message.message_id, message.sender_id ?? null,
      (message.sender_name ?? "").slice(0, 256), (message.username ?? "").slice(0, 128) || null,
      (message.text ?? "").slice(0, 4000), (message.media_type ?? "text").slice(0, 32),
      message.is_bot ? 1 : 0, message.date ?? null,
    ).run();
  }

  async listCommunityMessages(options: {
    chatId: number; limit?: number; beforeMessageId?: number | null; query?: string; sender?: string;
  }): Promise<{ items: Array<Record<string, unknown>>; has_more: boolean }> {
    const limit = Math.max(1, Math.min(100, Math.trunc(options.limit ?? 50)));
    const query = (options.query ?? "").trim().slice(0, 100);
    const sender = (options.sender ?? "").trim().slice(0, 80);
    const result = await this.db.prepare(
      `SELECT message_id, sender_id, sender_name, username, body, media_type, is_bot, created_at
       FROM fxi_community_messages
       WHERE chat_id = ? AND (? IS NULL OR message_id < ?)
         AND (? = '' OR instr(lower(body), lower(?)) > 0)
         AND (? = '' OR instr(lower(sender_name), lower(?)) > 0
           OR instr(lower(COALESCE(username, '')), lower(?)) > 0
           OR instr(CAST(COALESCE(sender_id, '') AS TEXT), ?) > 0)
       ORDER BY message_id DESC LIMIT ?`,
    ).bind(
      options.chatId, options.beforeMessageId ?? null, options.beforeMessageId ?? null,
      query, query, sender, sender, sender, sender, limit + 1,
    ).all<Record<string, unknown>>();
    const rows = result.results ?? [];
    return { items: rows.slice(0, limit), has_more: rows.length > limit };
  }

  async getCommunityMessage(chatId: number, messageId: number): Promise<Record<string, unknown> | null> {
    return this.db.prepare(
      "SELECT message_id, sender_id, sender_name, username, body, media_type, is_bot, created_at FROM fxi_community_messages WHERE chat_id = ? AND message_id = ?",
    ).bind(chatId, messageId).first<Record<string, unknown>>();
  }

  async deleteCommunityMessage(chatId: number, messageId: number): Promise<boolean> {
    const result = await this.db.prepare(
      "DELETE FROM fxi_community_messages WHERE chat_id = ? AND message_id = ?",
    ).bind(chatId, messageId).run();
    return (result.meta.changes ?? 0) > 0;
  }

  async editBotCommunityMessage(chatId: number, messageId: number, text: string): Promise<boolean> {
    const result = await this.db.prepare(
      "UPDATE fxi_community_messages SET body = ? WHERE chat_id = ? AND message_id = ? AND is_bot = 1",
    ).bind(text.slice(0, 4000), chatId, messageId).run();
    return (result.meta.changes ?? 0) > 0;
  }
}
