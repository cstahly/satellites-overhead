package com.sdr.satellites.model

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class SchedulerStatus(
    val state: String,
    val live: Boolean,
    val pid: Int,
    @SerialName("updated_at") val updatedAt: String,
    @SerialName("current_job") val currentJob: CurrentJob? = null,
    val message: String,
    val fresh: Boolean,
    @SerialName("status_age_s") val statusAgeSeconds: Double,
    @SerialName("queue_count") val queueCount: Int,
)

@Serializable
data class CurrentJob(
    val type: String,
    val label: String,
    @SerialName("fire_time") val fireTime: String? = null,
    @SerialName("command_id") val commandId: String? = null,
    @SerialName("frequency_hz") val frequencyHz: Double? = null,
    @SerialName("duration_s") val durationSeconds: Int? = null,
    @SerialName("lna_gain") val lnaGain: Int? = null,
    @SerialName("vga_gain") val vgaGain: Int? = null,
    val amp: Int? = null,
    val output: String? = null,
)

@Serializable
data class TrackPoint(
    val t: String,
    val az: Double,
    val el: Double,
    @SerialName("sub_lat") val subLat: Double,
    @SerialName("sub_lon") val subLon: Double,
)

@Serializable
data class Pass(
    val norad: Int,
    val name: String,
    val aos: String,
    val los: String,
    @SerialName("max_t") val maxTime: String,
    @SerialName("max_el") val maxElevation: Double,
    @SerialName("max_az") val maxAzimuth: Double,
    @SerialName("aos_az") val aosAzimuth: Double,
    @SerialName("los_az") val losAzimuth: Double,
    @SerialName("duration_s") val durationSeconds: Int,
    @SerialName("track_step_s") val trackStepSeconds: Int = 30,
    val track: List<TrackPoint> = emptyList(),
)

@Serializable
data class Capture(
    val id: String,
    val norad: Int,
    val name: String,
    val profile: String? = null,
    val source: String? = null,
    @SerialName("frequency_hz") val frequencyHz: Double? = null,
    @SerialName("lna_gain") val lnaGain: Int? = null,
    @SerialName("vga_gain") val vgaGain: Int? = null,
    val amp: Int? = null,
    val label: String? = null,
    @SerialName("started_at") val startedAt: String? = null,
    @SerialName("ended_at") val endedAt: String? = null,
    val output: String? = null,
    @SerialName("output_type") val outputType: String? = null,
    @SerialName("size_bytes") val sizeBytes: Long? = null,
    @SerialName("cadu_bytes") val caduBytes: Long? = null,
    @SerialName("report_path") val reportPath: String? = null,
)

@Serializable
data class Rule(
    val id: String,
    val enabled: Boolean,
    val type: String,
    val name: String,
    val norad: Int,
    val group: String? = null,
    @SerialName("frequency_hz") val frequencyHz: Double? = null,
    val profile: String? = null,
    @SerialName("min_peak_el") val minPeakElevation: Double? = null,
    @SerialName("start_offset_s") val startOffsetSeconds: Int? = null,
    @SerialName("end_offset_s") val endOffsetSeconds: Int? = null,
    @SerialName("lna_gain") val lnaGain: Int? = null,
    @SerialName("vga_gain") val vgaGain: Int? = null,
    val amp: Int? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
)

@Serializable
data class SdrEvent(
    val id: String,
    val type: String,
    val source: String? = null,
    @SerialName("ts") val timestamp: String,
    val data: JsonObject? = null,
)

@Serializable
data class ScanNowRequest(
    val norad: Int,
    val name: String? = null,
    @SerialName("duration_s") val durationSeconds: Int = 300,
    @SerialName("max_el") val maxElevation: Double? = null,
)
