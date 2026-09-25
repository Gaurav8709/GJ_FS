import './ZoneOverlay.css';

export default function ZoneOverlay({ zones }) {
  if (!zones || zones.length === 0) return null;

  return (
    <div className="zone-overlay-container">
      {zones
        .filter(z => !(z.zone_name || z.name || '').toLowerCase().includes('customer'))
        .map(zone => {
        let pointsString = '';
        let minX = 1, minY = 1, maxX = 0, maxY = 0;

        // Backend uses zone.polygon_points with [{"x": 0.1, "y": 0.1}, ...]
        // Support array of objects or array of arrays
        const points = zone.polygon_points || zone.coordinates || [];

        points.forEach(pt => {
          let x, y;
          if (Array.isArray(pt)) {
            [x, y] = pt;
          } else {
            x = pt.x;
            y = pt.y;
          }
          
          minX = Math.min(minX, x);
          minY = Math.min(minY, y);
          maxX = Math.max(maxX, x);
          maxY = Math.max(maxY, y);
          
          // Convert 0-1 scale to 0-100 scale for SVG preserveAspectRatio
          pointsString += `${x * 100},${y * 100} `;
        });

        if (!pointsString) return null;

        const width = maxX - minX;
        const height = maxY - minY;
        const color = zone.color || '#ff4444';

        return (
          <div key={zone.id} className="zone-wrapper">

            <div 
              className="zone-label"
              style={{
                left: `${(minX + width/2) * 100}%`,
                top: `${(minY + height/2) * 100}%`,
                background: color
              }}
            >
              {zone.zone_name || zone.name}
            </div>
          </div>
        );
      })}
    </div>
  );
}
