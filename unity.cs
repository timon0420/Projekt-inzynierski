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
    }
}