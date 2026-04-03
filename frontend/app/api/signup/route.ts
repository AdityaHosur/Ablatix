import { NextResponse } from "next/server";
import { getDB } from "@/lib/db";
import bcrypt from "bcryptjs";

export async function POST(req: Request) {
  const { name, email, password } = await req.json();

  const db = await getDB();

  await db.exec(`
    CREATE TABLE IF NOT EXISTS users (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT,
      email TEXT UNIQUE,
      password TEXT
    )
  `);

  const hashed = await bcrypt.hash(password, 10);

  try {
    await db.run(
      "INSERT INTO users (name,email,password) VALUES (?,?,?)",
      [name, email, hashed]
    );

    return NextResponse.json({
  success: true,
  user: { name, email }
});
  } catch {
    return NextResponse.json({ success: false, message: "User exists" });
  }
}