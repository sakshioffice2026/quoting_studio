import os
os.chdir('D:\\Quoting Studio\\quoting_studio')

from sqlalchemy import create_engine
engine = create_engine('mysql+pymysql://root:root@localhost:3306/quoting_studio')
conn = engine.connect()

result = conn.execute('SELECT count(*) FROM cad_profiles')
print(f'Total cad_profiles: {result.scalar()}')

result2 = conn.execute('SELECT role, count(*) FROM cad_profiles GROUP BY role')
print('Profiles by role:')
for row in result2:
    print(f'  role={row[0]}: {row[1]}')

# Check for cill specifically
result3 = conn.execute("SELECT * FROM cad_profiles WHERE role LIKE '%cill%'")
print(f'\nCill profiles:')
for row in result3:
    print(f'  id={row[0]} code={row[1]} name={row[2]} role={row[3]} material={row[4]} is_active={row[5]} is_default={row[6]}')