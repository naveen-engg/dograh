from dotenv import load_dotenv
load_dotenv('api/.env')
import asyncio
from api.db import db_client

async def main():
    u = await db_client.get_user_by_email('naveenkumar10k@gmail.com')
    if u:
        print(f"Found user: {u.id}, email={u.email}, current_role={u.effective_role.value}")
        await db_client.update_user_role(u.id, 'super_admin')
        refreshed = await db_client.get_user_by_id(u.id)
        print(f"Updated role to: {refreshed.effective_role.value}, is_superuser={refreshed.is_superuser}")
    else:
        print("User naveenkumar10k@gmail.com not found")

if __name__ == '__main__':
    asyncio.run(main())
