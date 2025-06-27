from pymongo import MongoClient
import os
import datetime

mongo_uri = os.environ.get('MONGO_URI')
client = MongoClient(mongo_uri)
db = client['koshur']
lessons = db['lessons']
count = 0
for lesson in lessons.find():
    dc = lesson.get('date_created')
    if isinstance(dc, str):
        try:
            # Try parsing common formats
            if '-' in dc:
                dt = datetime.datetime.strptime(dc, '%Y-%m-%d')
            else:
                dt = datetime.datetime.strptime(dc, '%B %d, %Y')
            lessons.update_one({'_id': lesson['_id']}, {'$set': {'date_created': dt}})
            count += 1
        except Exception as e:
            print(f'Could not convert lesson {lesson.get("title")} ({lesson.get("_id")}): {e}')
print(f'Migrated {count} lessons.') 