package com.sdr.satellites.api

import com.sdr.satellites.model.Capture
import com.sdr.satellites.model.CurrentJob
import com.sdr.satellites.model.Pass
import com.sdr.satellites.model.Rule
import com.sdr.satellites.model.ScanNowRequest
import com.sdr.satellites.model.SdrEvent
import com.sdr.satellites.model.SchedulerStatus
import io.ktor.client.HttpClient
import io.ktor.client.call.body
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.HttpTimeout
import io.ktor.client.plugins.logging.LogLevel
import io.ktor.client.plugins.logging.Logging
import io.ktor.client.request.delete
import io.ktor.client.request.get
import io.ktor.client.request.header
import io.ktor.client.request.parameter
import io.ktor.client.request.post
import io.ktor.client.request.setBody
import io.ktor.http.ContentType
import io.ktor.http.contentType
import io.ktor.serialization.kotlinx.json.json
import kotlin.native.HiddenFromObjC
import kotlinx.serialization.json.Json

class SatellitesApi(private val baseUrl: String, token: String) {
    private val authHeader = "Bearer $token"

    private val client = HttpClient {
        expectSuccess = true  // throw ResponseException on 4xx/5xx before body is touched
        install(ContentNegotiation) {
            json(Json {
                ignoreUnknownKeys = true
                isLenient = true
            })
        }
        install(HttpTimeout) {
            requestTimeoutMillis = 15_000
            connectTimeoutMillis = 10_000
        }
        install(Logging) { level = LogLevel.NONE }
    }

    @Throws(Exception::class)
    suspend fun getStatus(): SchedulerStatus =
        client.get("$baseUrl/api/v1/status") {
            header("Authorization", authHeader)
        }.body()

    @Throws(Exception::class)
    suspend fun getRules(): List<Rule> =
        client.get("$baseUrl/api/v1/rules") {
            header("Authorization", authHeader)
        }.body()

    @Throws(Exception::class)
    suspend fun getPasses(
        norad: Int,
        hours: Int = 24,
        minEl: Double = 10.0,
        lat: Double,
        lon: Double,
        altM: Double = 180.0,
    ): List<Pass> =
        client.get("$baseUrl/api/v1/passes") {
            header("Authorization", authHeader)
            parameter("norad", norad)
            parameter("hours", hours)
            parameter("min_el", minEl)
            parameter("lat", lat)
            parameter("lon", lon)
            parameter("alt_m", altM)
            parameter("track_step_s", 30)
        }.body()

    @Throws(Exception::class)
    suspend fun getCaptures(norad: Int = -1, limit: Int = 50): List<Capture> =
        client.get("$baseUrl/api/v1/captures") {
            header("Authorization", authHeader)
            if (norad > 0) parameter("norad", norad)
            parameter("limit", limit)
        }.body()

    @Throws(Exception::class)
    suspend fun getEvents(after: String? = null, limit: Int = 50): List<SdrEvent> =
        client.get("$baseUrl/api/v1/events") {
            header("Authorization", authHeader)
            after?.let { parameter("after", it) }
            parameter("limit", limit)
        }.body()

    @Throws(Exception::class)
    suspend fun triggerScanNow(request: ScanNowRequest) {
        client.post("$baseUrl/api/v1/scans") {
            header("Authorization", authHeader)
            contentType(ContentType.Application.Json)
            setBody(request)
        }
    }

    @Throws(Exception::class)
    suspend fun setRuleEnabled(ruleId: String, enabled: Boolean) {
        client.post("$baseUrl/api/v1/rules") {
            header("Authorization", authHeader)
            contentType(ContentType.Application.Json)
            setBody(mapOf("id" to ruleId, "enabled" to enabled))
        }
    }

    fun close() = client.close()
}
