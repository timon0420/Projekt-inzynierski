using UnityEngine;
using UnityEngine.Networking;
using System;
using System.Collections;
using System.ID;
using System.Net.WebSockets;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

public class WebSocketClient : MonoBehaviour
{
    [Header("WebSocket Settings")]
    public string serverUrl = "ws://localhost:8080";
    public string sessionCode = "";
    public bool showConnectionPanel = true;

    [Header("Robot Settings")]
    public Transform[] joints;

    [Header("Lerp Settings")]
    public float lerpSpeed = 10f;
    
    private ClientWebSocket webSocket;
    private CancellationTokenSource cancellationTokenSource;
    private string token;
    private string webSocketPath = "/ws/unity";
    private string status = "Write your session code and click Connect";
    private bool connecting;

    private float[] lastReceivedAngles = new float[6];
    private bool newDataReceived = false;
    private readonly object dataLock = new object();

    [Serializable]
    private class PairRequest
    {
        public string code;
        public string role;
    }

    [Serializable]
    private class PairResponse
    {
        public string token;
        public string websocketPath;
        public string error;
    }

    [Serializable]
    private class RobotData
    {
        public string type;
        public float[] angles;
        public double timestamp;
        public long sequence;
    }
    
    private void OnGUI()
    {
        if (!showConnectionPanel)
            return;

        GUI.Box(new Rect(20, 20, 390, 180), "WebSocket Connection");
        GUI.Label(new Rect(40, 55, 95, 25), "Server");
        serverUrl = GUI.TextField(new Rect(140, 55, 200, 25), serverUrl);
        GUI.Label(new Rect(40, 85, 95, 25), "Session Code");
        sessionCode = GUI.TextField(new Rect(140, 85, 200, 25), sessionCode.ToUpperInvariant(), 9);
        GUI.enabled = !connecting && !string.IsNullOrWhiteSpace(sessionCode);

        if (GUI.Button(new Rect(135, 125, 160, 30), connecting ? "Connecting..." : "Connect"))
            ConnectWithSessionCode();

        GUI.enabled = true;
        GUI.Label(new Rect(40, 165, 95, 25), "Status");
        GUI.Label(new Rect(140, 165, 200, 25), status);
    }

    public void ConnectWithSessionCode()
    {
        if (connecting)
            return;

        cancellationTokenSource?.Cancel();
        cancellationTokenSource?.Dispose();
        cancellationTokenSource = new CancellationTokenSource();
        token = null;
        connecting = true;
        status = "Connecting...";
        StartCoroutine(PairAndConnect());
    }

    private IEnumerator PairAndConnect()
    {
        string baseUrl = serverUrl.TrimEnd('/');

        PairRequest pairRequest = new PairRequest
        {
            code = sessionCode.Trim(),
            role = "unity"
        };

        byte[] body = Encoding.UTF8.GetBytes(JsonUtility.ToJson(pairRequest));

        using (UnityWebRequest request = new UnityWebRequest(baseUrl + "/api/sessions/pair", "POST"))
        {
            request.uploadHandler = new UploadHandlerRaw(body);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            yield return request.SendWebRequest();

            if (request.result != UnityWebRequest.Result.Success)
            {
                PairResponse errorResponse = JsonUtility.FromJson<PairResponse>(request.downloadHandler.text);
                status = errorResponse != null && !string.IsNullOrEmpty(errorResponse.error) ? "Error: " + errorResponse.error : "Error: " + request.error;
                connecting = false;
                yield break;
            }

            PairResponse response = JsonUtility.FromJson<PairResponse>(request.downloadHandler.text);

            token = response.token;
            webSocketPath = string.IsNullOrEmpty(response.websocketPath) ? "/ws/unity" : response.websocketPath;
        }

        _ = RunConnectionLoop(cancellationTokenSource.Token);
    }

    private async Task RunConnectionLoop(CancellationToken cancellationToken)
    {
        int delay = 1;

        while (!cancellationToken.IsCancellationRequested)
        {
            try
            {
                webSocket?.Dispose();
                webSocket = new ClientWebSocket();
                status = "Connecting to WebSocket...";
                await webSocket.ConnectAsync(BuildWebSocketUri(), cancellationToken);
                status = "Connected to WebSocket";
                connecting = false;
                delay = 1;
                await ReceiveLoop(webSocket, cancellationToken);
            } catch (OperationCanceledException)
            {
                break;
            } catch (Exception e)
            {
                status = "Connection error: " + e.Message;
                connection = false;
            } finally
            {
                webSocket?.Dispose();
                webSocket = null;
            }

            if (!cancellationToken.IsCancellationRequested)
            {
                status = "Disconnected. Reconnecting in " + delay + " seconds...";

                try
                {
                    await Task.Delay(TimeSpan.FromSeconds(delay), cancellationToken);
                } catch (OperationCanceledException)
                {
                    break;
                }

                delay = Math.Min(delay * 2, 30);
            }
        }
    }

    private Uri BuildWebSocketUri()
    {
        Uri baseUri = new Uri(serverUrl.TrimEnd('/'));
        string scheme = baseUri.Scheme == "https" ? "wss" : "ws";
        UriBuilder uriBuilder = new UriBuilder(scheme, baseUri.Host, baseUri.IsDefaultPort ? -1 : baseUri.Port)
        {
            Path = webSocketPath,
            Query = "token=" + Uri.EscapeDataString(token)
        };
        return uriBuilder.Uri;
    }

    private async Task ReceiveLoop(ClientWebSocket webSocket, CancellationToken cancellationToken)
    {
        byte[] buffer = new byte[4096];

        while (webSocket.State == WebSocketState.Open && !cancellationToken.IsCancellationRequested)
        {
            using (MemoryStream ms = new MemoryStream())
            {
                WebSocketReceiveResult result;

                do
                {
                    result = await webSocket.ReceiveAsync(new ArraySegment<byte>(buffer), cancellationToken);

                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        await webSocket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "Closing", cancellationToken);
                        return;
                    }

                    ms.Write(buffer, 0, result.Count);
                }
                while (!result.EndOfMessage);

                if (result.MessageType != WebSocketMessageType.Text)
                    continue;
                
                string message = Encoding.UTF8.GetString(ms.ToArray());
                RobotData data = JsonUtility.FromJson<RobotData>(message);

                if (data == null || data.type != "angles" || data.angles == null || data.angles.Length != 6)
                    continue;

                lock (dataLock)
                {
                    lastReceivedAngles = data.angles;
                    newDataReceived = true;
                }
            }
        }
    }

    private void Update()
    {
        float[] angles = null;
        lock(dataLock)
        {
            if (newDataReceived)
            {
                angles = lastReceivedAngles;
                newDataReceived = false;
            }
        }

        if (angles != null)
            ApplyAnglesToRobot(angles);
    }

    private void ApplyAnglesToRobot(float[] angles)
    {
        int jointCount = Math.Min(joints.Length, angles.Length);

        for (int i = 0; i < jointCount; i++)
        {
            if (joints[i] == null)
                continue;
            
            Quaternion targetRotation = Quaternion.Euler(0, angles[i], 0);
            joints[i].localRotation = Quaternion.Slerp(
                joints[i].localRotation,
                targetRotation,
                Time.deltaTime * lerpSpeed
            );
        }
    }

    private async void OnApplicationQuit()
    {
        cancellationTokenSource?.Cancel();

        if (webSocket != null && webSocket.State == WebSocketState.Open)
        {
            try
            {
                await webSocket.CloseAsync(WebSocketCloseStatus.NormalClosure, "Application quitting", CancellationToken.None);
            }
            catch (Exception e)
            {
                Debug.LogError("Error closing WebSocket: " + e.Message);
            }
        }
        webSocket?.Dispose();
        cancellationTokenSource?.Dispose();
    }
}