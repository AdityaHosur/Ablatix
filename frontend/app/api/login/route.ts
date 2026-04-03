import { NextResponse } from "next/server";
import { getDB } from "@/lib/db";
import bcrypt from "bcryptjs";

export async function POST(req: Request) {
  const { email, password } = await req.json();

  const db = await getDB();

  const user = await db.get(
    "SELECT * FROM users WHERE email = ?",
    [email]
  );

  if (!user) return NextResponse.json({ success: false });

  const match = await bcrypt.compare(password, user.password);

  if (!match) return NextResponse.json({ success: false });

  return NextResponse.json({
    success: true,
    user: { name: user.name, email: user.email },
  });
}