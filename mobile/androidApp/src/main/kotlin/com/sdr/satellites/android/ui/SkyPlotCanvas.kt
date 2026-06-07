package com.sdr.satellites.android.ui

import android.graphics.Paint
import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import com.sdr.satellites.model.OverheadSat
import com.sdr.satellites.model.TrackPoint
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

@Composable
fun SkyPlotCanvas(
    modifier: Modifier = Modifier,
    trackPoints: List<TrackPoint> = emptyList(),
    overheadSats: List<OverheadSat> = emptyList(),
    selectedNorad: Int? = null,
) {
    Canvas(
        modifier = modifier.clip(CircleShape),
    ) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val r = minOf(cx, cy) - 28f

        // Background
        drawCircle(color = Color(0xFF0D1117), radius = minOf(cx, cy))

        // Elevation rings: 0°(edge), 30°, 60°
        for (el in listOf(0f, 30f, 60f)) {
            val ringR = r * (1f - el / 90f)
            drawCircle(
                color = if (el == 0f) Color.White.copy(alpha = 0.35f) else Color.White.copy(alpha = 0.12f),
                radius = ringR,
                center = Offset(cx, cy),
                style = Stroke(width = if (el == 0f) 2f else 1f),
            )
        }

        // Crosshairs
        drawLine(Color.White.copy(alpha = 0.08f), Offset(cx, cy - r), Offset(cx, cy + r), strokeWidth = 1f)
        drawLine(Color.White.copy(alpha = 0.08f), Offset(cx - r, cy), Offset(cx + r, cy), strokeWidth = 1f)

        drawIntoCanvas { canvas ->
            val labelPaint = Paint().apply {
                color = Color(0xFF8B949E).toArgb()
                textSize = 22f
                typeface = Typeface.DEFAULT_BOLD
                textAlign = Paint.Align.CENTER
            }
            val elPaint = Paint().apply {
                color = Color(0xFF8B949E).copy(alpha = 0.6f).toArgb()
                textSize = 18f
                textAlign = Paint.Align.LEFT
            }

            // Compass labels N/E/S/W
            val dirs = listOf("N" to 0.0, "E" to 90.0, "S" to 180.0, "W" to 270.0)
            for ((label, az) in dirs) {
                val rad = ((az - 90.0) * PI / 180.0).toFloat()
                val px = cx + (r + 20f) * cos(rad)
                val py = cy + (r + 20f) * sin(rad) + 8f
                canvas.nativeCanvas.drawText(label, px, py, labelPaint)
            }

            // Elevation ring labels
            for (el in listOf(30f, 60f)) {
                val ringR = r * (1f - el / 90f)
                canvas.nativeCanvas.drawText("${el.toInt()}°", cx + 4f, cy - ringR + 18f, elPaint)
            }

            // Track arc for pass detail
            if (trackPoints.isNotEmpty()) {
                val pts = trackPoints.map { azElToOffset(it.az, it.el, cx, cy, r) }
                if (pts.size > 1) {
                    val path = Path()
                    path.moveTo(pts[0].x, pts[0].y)
                    pts.drop(1).forEach { path.lineTo(it.x, it.y) }
                    drawPath(
                        path,
                        color = Color(0xFF39D98A).copy(alpha = 0.85f),
                        style = Stroke(width = 3f, cap = StrokeCap.Round, join = StrokeJoin.Round),
                    )
                }
                // AOS dot
                trackPoints.firstOrNull()?.let {
                    val pos = azElToOffset(it.az, it.el, cx, cy, r)
                    drawCircle(Color(0xFF39D98A), 7f, pos)
                    canvas.nativeCanvas.drawText("AOS", pos.x + 10f, pos.y + 6f,
                        Paint().apply { color = Color(0xFF39D98A).toArgb(); textSize = 18f })
                }
                // LOS dot
                trackPoints.lastOrNull()?.let {
                    val pos = azElToOffset(it.az, it.el, cx, cy, r)
                    drawCircle(Color(0xFFFF8C00), 7f, pos)
                    canvas.nativeCanvas.drawText("LOS", pos.x + 10f, pos.y + 6f,
                        Paint().apply { color = Color(0xFFFF8C00).toArgb(); textSize = 18f })
                }
                // Peak dot (max elevation)
                trackPoints.maxByOrNull { it.el }?.let {
                    val pos = azElToOffset(it.az, it.el, cx, cy, r)
                    drawCircle(Color.White, 8f, pos)
                    canvas.nativeCanvas.drawText("%.0f°".format(it.el), pos.x + 12f, pos.y + 6f,
                        Paint().apply { color = android.graphics.Color.WHITE; textSize = 18f; typeface = Typeface.DEFAULT_BOLD })
                }
            }

            // Overhead satellites
            val satNamePaint = Paint().apply { textSize = 20f }
            for (sat in overheadSats) {
                val pos = azElToOffset(sat.az, sat.el, cx, cy, r)
                val isSelected = selectedNorad == sat.norad
                val brightness = (0.35f + 0.65f * (sat.el / 90.0)).toFloat()
                val color = if (isSelected) Color(0xFF4DFF80) else Color(0xFF59D1FF).copy(alpha = brightness)
                val dotR = when {
                    isSelected -> 10f
                    sat.el > 60 -> 8f
                    else -> 6f
                }
                drawCircle(color, dotR, pos)
                if (overheadSats.size <= 60 || isSelected) {
                    satNamePaint.color = color.copy(alpha = if (isSelected) 1f else (0.4f + 0.6f * (sat.el / 90f).toFloat())).toArgb()
                    canvas.nativeCanvas.drawText(sat.name.take(16), pos.x + dotR + 4f, pos.y + 6f, satNamePaint)
                }
            }

            // Count label for overhead
            if (overheadSats.isNotEmpty()) {
                canvas.nativeCanvas.drawText(
                    "${overheadSats.size} overhead",
                    cx,
                    cy + r + 22f,
                    Paint().apply { color = Color(0xFF8B949E).toArgb(); textSize = 18f; textAlign = Paint.Align.CENTER },
                )
            }
        }
    }
}

private fun azElToOffset(az: Double, el: Double, cx: Float, cy: Float, r: Float): Offset {
    val dist = r * (1.0 - el / 90.0).toFloat()
    val rad = ((az - 90.0) * PI / 180.0).toFloat()
    return Offset(cx + dist * cos(rad), cy + dist * sin(rad))
}
