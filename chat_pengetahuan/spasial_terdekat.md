---
judul: Pola query terdekat/jarak (PostGIS)
kata_kunci: [terdekat, terjauh, jarak, radius, sekitar, dekat, jangkauan]
---
Contoh pola query terdekat (pelabuhan -> Kantor SAR):
SELECT p.nama_pelabuhan, k.attrs->>'nama_kantor' AS kantor_sar, round((ST_Distance(ST_SetSRID(ST_MakePoint(p.lon,p.lat),4326)::geography, k.geom::geography)/1000)::numeric,1) AS jarak_km, p.lat, p.lon FROM pelabuhan_daerah p CROSS JOIN LATERAL (SELECT attrs, geom FROM map_layers WHERE provinsi='BASARNAS' AND layer='KANTOR SAR' ORDER BY geom <-> ST_SetSRID(ST_MakePoint(p.lon,p.lat),4326) LIMIT 1) k WHERE p.provinsi ILIKE '%maluku utara%' AND p.lat IS NOT NULL ORDER BY jarak_km DESC
