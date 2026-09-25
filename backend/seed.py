import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import engine, Base, async_session
from app.models.user import User, CameraAccess
from app.models.floor import Floor, Section
from app.models.camera import Camera, CameraZone
from app.models.new_features import ForensicClip, FootfallRecord, EmployeeFace, CameraHeatmap
from app.utils.auth import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

async def init_db():
    logger.info("Dropping and recreating all tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Tables created.")


async def seed_data():
    async with async_session() as session:
        # Check if admin already exists
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            logger.info("Admin already exists, skipping seed.")
            return

        # 1. Add Super Admin
        logger.info("Creating admin user...")
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            name="Super Admin",
            role="admin",
            email="admin@gjfashion.local"
        )
        session.add(admin)
        await session.flush()

        # 2. Add Floors
        logger.info("Creating floors...")
        floors = [
            Floor(name="GF - Menswear", code="GF", sort_order=0),
            Floor(name="F1 - Womenswear", code="F1", sort_order=1),
            Floor(name="F2 - Kids & Accessories", code="F2", sort_order=2)
        ]
        session.add_all(floors)
        await session.flush()
        
        # Add Sections
        logger.info("Creating sections...")
        sections = []
        gf_sections = ["Formals", "Casuals", "Ethnic", "Accessories"]
        for s in gf_sections:
            code = f"GF-{s[:4].upper()}"
            sections.append(Section(name=s, code=code, floor_id=floors[0].id))
            
        f1_sections = ["Western", "Ethnic", "Bridal", "Loungewear"]
        for s in f1_sections:
            code = f"F1-{s[:4].upper()}"
            sections.append(Section(name=s, code=code, floor_id=floors[1].id))
            
        f2_sections = ["Boys", "Girls", "Infants", "Bags & Footwear"]
        for s in f2_sections:
            code = f"F2-{s[:4].upper()}"
            sections.append(Section(name=s, code=code, floor_id=floors[2].id))
            
        session.add_all(sections)
        await session.flush()

        # 3. Add Cameras (27 cameras)
        logger.info("Creating 27 cameras...")
        cameras = []
        for i in range(1, 28):
            # Assign floors: 1-9 to GF, 10-18 to F1, 19-27 to F2
            if i <= 9:
                f_id = floors[0].id
            elif i <= 18:
                f_id = floors[1].id
            else:
                f_id = floors[2].id
                
            cam = Camera(
                cam_id=f"cam{i}",
                name=f"Camera {i}",
                floor_id=f_id,
                rtsp_url="",
                active=True
            )
            cameras.append(cam)
        
        session.add_all(cameras)
        await session.flush()
        
        # 4. Add Zones to first few cameras as example
        logger.info("Creating sample zones...")
        zone1 = CameraZone(
            camera_id=cameras[0].id,
            zone_name="Formals Area",
            zone_type="monitoring",
            polygon_points=[{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}],
            color="#FF0000",
            required_count=1
        )
        session.add(zone1)

        # Give admin access to all cameras
        access_entries = [CameraAccess(user_id=admin.id, camera_id=f"cam{i}", granted_by="system") for i in range(1, 28)]
        session.add_all(access_entries)

        # 5. Add Sample Employees for Face Alert
        logger.info("Creating sample employee records...")
        emp1 = EmployeeFace(emp_id="EMP-101", emp_name="Rahul Sharma", department="Menswear", role="Senior Sales Executive", face_url="https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150")
        emp2 = EmployeeFace(emp_id="EMP-102", emp_name="Priya Patel", department="Womenswear", role="Floor Manager", face_url="https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=150")
        emp3 = EmployeeFace(emp_id="EMP-103", emp_name="Amit Verma", department="Inventory", role="Store Supervisor", face_url="https://images.unsplash.com/photo-1507003211169-0a1dd7228f2d?w=150")
        session.add_all([emp1, emp2, emp3])

        # 6. Add Sample Footfall Data
        logger.info("Creating sample footfall analytics...")
        import datetime
        now = datetime.datetime.utcnow()
        footfall_samples = []
        for h in range(8):
            ts = now - datetime.timedelta(hours=8 - h)
            footfall_samples.append(FootfallRecord(
                cam_id="cam1",
                entries=15 + h * 3,
                exits=10 + h * 2,
                net_count=5 + h,
                male_count=8 + h,
                female_count=7 + h * 2,
                age_18_25=5 + h,
                age_26_35=6 + h,
                age_36_50=3 + h,
                age_50_plus=1 + h,
                timestamp=ts
            ))
        session.add_all(footfall_samples)

        # 7. Add Sample Forensic & Assigned Employee Clips
        logger.info("Creating sample assigned employee video clips...")
        clip1 = ForensicClip(
            title="Rahul Sharma - Face Embedding Video (Morning Shift)",
            category="assign_employee",
            cam_id="cam1",
            emp_id="EMP-101",
            emp_name="Rahul Sharma",
            role="Senior Sales Executive",
            shift="Morning",
            file_url="/static/sample_emp1.mp4",
            metadata_json={"duration_seconds": 120, "quality": "1080p"},
            listener_json={"clip_id": 1, "emp_id": "EMP-101", "emp_name": "Rahul Sharma", "role": "Senior Sales Executive", "shift": "Morning", "status": "ready_for_cv_facial_embedding"},
            status="processed"
        )
        clip2 = ForensicClip(
            title="Priya Patel - Face Embedding Video (Night Shift)",
            category="assign_employee",
            cam_id="cam2",
            emp_id="EMP-102",
            emp_name="Priya Patel",
            role="Floor Manager",
            shift="Night",
            file_url="/static/sample_emp2.mp4",
            metadata_json={"duration_seconds": 90, "quality": "1080p"},
            listener_json={"clip_id": 2, "emp_id": "EMP-102", "emp_name": "Priya Patel", "role": "Floor Manager", "shift": "Night", "status": "ready_for_cv_facial_embedding"},
            status="processed"
        )
        session.add_all([clip1, clip2])

        # 8. Add Sample Heatmaps
        logger.info("Creating sample heatmaps...")
        hm1 = CameraHeatmap(
            cam_id="cam1",
            image_url="https://images.unsplash.com/photo-1555421689-491a97ff2040?w=600",
            peak_density=0.88,
            meta_info={"hotspot": "Formals Display Stand", "duration": "Peak 2 PM - 5 PM"}
        )
        session.add(hm1)

        await session.commit()
        logger.info("Seed data successfully inserted.")

async def main():
    await init_db()
    await seed_data()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
