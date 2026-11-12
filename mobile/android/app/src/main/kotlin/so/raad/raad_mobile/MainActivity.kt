package so.raad.raad_mobile

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.app.ActivityCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel
import kotlin.concurrent.thread

class MainActivity : FlutterActivity() {
    private val METHOD_CHANNEL = "so.raad.raad_mobile/audio"
    private val EVENT_CHANNEL = "so.raad.raad_mobile/mic_stream"
    private var audioRecord: AudioRecord? = null
    private var isRecording = false
    private var recordingThread: Thread? = null
    private var eventSink: EventChannel.EventSink? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        EventChannel(flutterEngine.dartExecutor.binaryMessenger, EVENT_CHANNEL).setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
                    eventSink = events
                }

                override fun onCancel(arguments: Any?) {
                    eventSink = null
                    stopAudioRecord()
                }
            }
        )

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, METHOD_CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "startRecording" -> {
                    if (ActivityCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                        ActivityCompat.requestPermissions(this, arrayOf(Manifest.permission.RECORD_AUDIO), 1001)
                        result.error("PERMISSION_DENIED", "RECORD_AUDIO permission not granted", null)
                        return@setMethodCallHandler
                    }
                    val started = startAudioRecord()
                    result.success(started)
                }
                "stopRecording" -> {
                    stopAudioRecord()
                    result.success(true)
                }
                "isRecording" -> {
                    result.success(isRecording)
                }
                else -> result.notImplemented()
            }
        }
    }

    private fun startAudioRecord(): Boolean {
        if (isRecording) return true
        val sampleRate = 8000
        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val minBufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)
        val bufferSize = Math.max(minBufferSize, 640) // 640 bytes = 320 16-bit PCM samples = 40ms

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                sampleRate,
                channelConfig,
                audioFormat,
                bufferSize
            )
            if (audioRecord?.state != AudioRecord.STATE_INITIALIZED) {
                audioRecord?.release()
                audioRecord = null
                return false
            }
            audioRecord?.startRecording()
            isRecording = true

            recordingThread = thread(start = true, name = "IntercomAudioRecordThread") {
                val buffer = ByteArray(640)
                while (isRecording && audioRecord != null) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: -1
                    if (read > 0) {
                        val chunk = if (read == buffer.size) buffer.clone() else buffer.copyOf(read)
                        runOnUiThread {
                            eventSink?.success(chunk)
                        }
                    }
                }
            }
            return true
        } catch (_: Exception) {
            stopAudioRecord()
            return false
        }
    }

    private fun stopAudioRecord() {
        isRecording = false
        try {
            recordingThread?.interrupt()
            recordingThread = null
            audioRecord?.stop()
            audioRecord?.release()
            audioRecord = null
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        stopAudioRecord()
        super.onDestroy()
    }
}
