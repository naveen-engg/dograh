/*
  Provides authentication token to LocalProviderWrapper once loaded
  in the browser.
  Returns 401 if no token cookie exists (user needs to log in).
*/
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

import { getServerBackendUrl } from '@/lib/apiClient';
import { getAuthProvider } from '@/lib/auth/config';
import { OSS_TOKEN_COOKIE, OSS_USER_COOKIE, sessionCookieOptions } from '@/lib/auth/cookies';

export async function GET(request: NextRequest) {
  const authProvider = await getAuthProvider();

  // Only handle OSS mode
  if (authProvider !== 'local') {
    return NextResponse.json({ error: 'Not in OSS mode' }, { status: 400 });
  }

  const cookieStore = await cookies();
  const token = cookieStore.get(OSS_TOKEN_COOKIE)?.value;
  const userCookie = cookieStore.get(OSS_USER_COOKIE)?.value;

  // If no token exists, return 401 (user needs to sign up or log in)
  if (!token) {
    return NextResponse.json({ error: 'Not authenticated' }, { status: 401 });
  }

  let user = userCookie ? JSON.parse(userCookie) : null;

  // Automatically refresh role and details from backend
  if (!user || !user.role) {
    try {
      const backendUrl = getServerBackendUrl();
      const meRes = await fetch(`${backendUrl}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (meRes.ok) {
        const meData = await meRes.json();
        user = {
          ...user,
          ...meData,
          provider: 'local',
        };
        const options = sessionCookieOptions(request, 60 * 60 * 24 * 30);
        cookieStore.set(OSS_USER_COOKIE, JSON.stringify(user), options);
      }
    } catch {
      // Fallback to cookie
    }
  }

  // Return the auth info as JSON
  return NextResponse.json({
    token,
    user: user || { id: token, name: 'Local User', provider: 'local' },
  });
}

