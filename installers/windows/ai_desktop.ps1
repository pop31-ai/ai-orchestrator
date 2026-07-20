Add-Type -AssemblyName PresentationFramework, PresentationCore, System.Net.Http, System.Web

# Character definitions
$chars = @(
    @{Name="Assistant";  Provider="local_tinyllama";    Avatar="🤖"; Color="#3fb950"; Model="Q4_K_M"; Desc="Balanced, docs & tools"; Loaded=$false},
    @{Name="Speedy";     Provider="local_tinyllama_q2"; Avatar="⚡"; Color="#d29922"; Model="Q2_K";   Desc="Fast responses"; Loaded=$false},
    @{Name="Thinker";    Provider="local_tinyllama_q3"; Avatar="📚"; Color="#58a6ff"; Model="Q3_K_M"; Desc="Creative, ideas"; Loaded=$false},
    @{Name="Analyst";    Provider="local_tinyllama_q5"; Avatar="🔌"; Color="#bc8cff"; Model="Q5_K_M"; Desc="Deep analysis"; Loaded=$false},
    @{Name="Scholar";    Provider="local_tinyllama_q8"; Avatar="⭐"; Color="#ff7b9c"; Model="Q8_0";   Desc="Best quality"; Loaded=$false}
)

$apiBase = "http://127.0.0.1:8080"
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(300)

# XAML Window
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        Title="AI Orchestrator Desktop" Height="450" Width="950" WindowStartupLocation="CenterScreen"
        Background="#0d1117" FontFamily="Segoe UI" ResizeMode="CanResize" MinWidth="700" MinHeight="350">
    <Window.Resources>
        <Style TargetType="Button"><Setter Property="Background" Value="#161b22"/><Setter Property="Foreground" Value="#c9d1d9"/><Setter Property="BorderBrush" Value="#30363d"/><Setter Property="BorderThickness" Value="1"/><Setter Property="Padding" Value="8,4"/><Setter Property="FontSize" Value="12"/></Style>
        <Style TargetType="TextBox"><Setter Property="Background" Value="#0d1117"/><Setter Property="Foreground" Value="#c9d1d9"/><Setter Property="BorderBrush" Value="#30363d"/><Setter Property="BorderThickness" Value="1"/><Setter Property="FontSize" Value="12"/></Style>
        <Style TargetType="TextBlock"><Setter Property="Foreground" Value="#c9d1d9"/></Style>
        <Style TargetType="ListBox"><Setter Property="Background" Value="#161b22"/><Setter Property="Foreground" Value="#c9d1d9"/><Setter Property="BorderBrush" Value="#30363d"/></Style>
    </Window.Resources>
    <Grid Margin="10">
        <Grid.RowDefinitions>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="Auto"/>
            <RowDefinition Height="*"/>
            <RowDefinition Height="Auto"/>
        </Grid.RowDefinitions>

        <!-- Header -->
        <StackPanel Grid.Row="0" Orientation="Horizontal" Margin="0,0,0,10">
            <TextBlock Text="⚡ AI Orchestrator Desktop" FontSize="20" FontWeight="Bold" VerticalAlignment="Center"/>
            <TextBlock x:Name="StatusText" Text="Loading..." FontSize="12" Margin="15,0,0,0" VerticalAlignment="Center" Foreground="#8b949e"/>
        </StackPanel>

        <!-- Character Tiles -->
        <WrapPanel Grid.Row="1" x:Name="CharPanel" Margin="0,0,0,10"/>

        <!-- Chat Area -->
        <Grid Grid.Row="2" Margin="0,0,0,5">
            <Grid.RowDefinitions>
                <RowDefinition Height="Auto"/>
                <RowDefinition Height="*"/>
                <RowDefinition Height="Auto"/>
            </Grid.RowDefinitions>
            <TextBlock Grid.Row="0" x:Name="ChatHeader" Text="💬 Select a character to chat" FontSize="14" FontWeight="SemiBold" Margin="0,0,0,5"/>
            <ListBox Grid.Row="1" x:Name="ChatBox" ScrollViewer.VerticalScrollBarVisibility="Auto" Margin="0,0,0,5"/>
            <Grid Grid.Row="2">
                <Grid.ColumnDefinitions>
                    <ColumnDefinition Width="*"/>
                    <ColumnDefinition Width="Auto"/>
                </Grid.ColumnDefinitions>
                <TextBox Grid.Column="0" x:Name="InputBox" Height="50" TextWrapping="Wrap" AcceptsReturn="True" VerticalScrollBarVisibility="Auto"/>
                <Button Grid.Column="1" x:Name="SendBtn" Content="Send" Width="70" Height="50" Margin="5,0,0,0" IsEnabled="False"/>
            </Grid>
        </Grid>

        <!-- Status Bar -->
        <StatusBar Grid.Row="3" Background="#161b22" BorderBrush="#30363d" BorderThickness="1">
            <StatusBarItem><TextBlock x:Name="TrayStatus" Text="🟢 Running" Foreground="#3fb950"/></StatusBarItem>
        </StatusBar>
    </Grid>
</Window>
'@

$reader = New-Object System.Xml.XmlNodeReader $xaml
$win = [Windows.Markup.XamlReader]::Load($reader)
$win.Add_MouseLeftButtonDown({ if ($_.ClickCount -eq 2) { $win.DragMove() } })

# Get controls
$charPanel = $win.FindName("CharPanel")
$chatBox = $win.FindName("ChatBox")
$inputBox = $win.FindName("InputBox")
$sendBtn = $win.FindName("SendBtn")
$chatHeader = $win.FindName("ChatHeader")
$statusText = $win.FindName("StatusText")
$trayStatus = $win.FindName("TrayStatus")

$currentChar = $null
$script:responses = @{}

# Create character tiles
function New-CharTile($char) {
    $border = New-Object Windows.Controls.Border
    $border.Width = 160; $border.Height = 170
    $border.Margin = "5"
    $border.CornerRadius = "8"
    $border.Background = "#161b22"
    $border.BorderBrush = "#30363d"
    $border.BorderThickness = "1"
    $border.Cursor = "Hand"

    $stack = New-Object Windows.Controls.StackPanel
    $stack.HorizontalAlignment = "Center"
    $stack.VerticalAlignment = "Center"

    # Avatar circle
    $avBorder = New-Object Windows.Controls.Border
    $avBorder.Width = 60; $avBorder.Height = 60
    $avBorder.CornerRadius = "30"
    $avBorder.Background = $char.Color
    $avBorder.HorizontalAlignment = "Center"

    $avText = New-Object Windows.Controls.TextBlock
    $avText.Text = $char.Avatar
    $avText.FontSize = 28
    $avText.HorizontalAlignment = "Center"
    $avText.VerticalAlignment = "Center"
    $avBorder.Child = $avText

    # Name
    $nameText = New-Object Windows.Controls.TextBlock
    $nameText.Text = $char.Name
    $nameText.FontSize = 15
    $nameText.FontWeight = "Bold"
    $nameText.HorizontalAlignment = "Center"
    $nameText.Margin = "0,8,0,0"

    # Status dot + model
    $statusStack = New-Object Windows.Controls.StackPanel
    $statusStack.Orientation = "Horizontal"
    $statusStack.HorizontalAlignment = "Center"

    $dot = New-Object Windows.Controls.TextBlock
    $dot.Text = "●"
    $dot.Foreground = if ($char.Loaded) { "#3fb950" } else { "#da3633" }
    $dot.FontSize = 10
    $dot.Margin = "0,2,4,0"

    $modelText = New-Object Windows.Controls.TextBlock
    $modelText.Text = $char.Model
    $modelText.FontSize = 11
    $modelText.Foreground = "#58a6ff"

    $statusStack.Children.Add($dot)
    $statusStack.Children.Add($modelText)

    # Description
    $descText = New-Object Windows.Controls.TextBlock
    $descText.Text = $char.Desc
    $descText.FontSize = 10
    $descText.Foreground = "#8b949e"
    $descText.HorizontalAlignment = "Center"
    $descText.Margin = "0,4,0,0"

    $stack.Children.Add($avBorder)
    $stack.Children.Add($nameText)
    $stack.Children.Add($statusStack)
    $stack.Children.Add($descText)
    $border.Child = $stack

    # Click to chat
    $border.Add_MouseLeftButtonDown({
        $script:currentChar = $char.Provider
        $script:chatHeader.Text = "💬 Chatting with $($char.Name) ($($char.Model))"
        $sendBtn.IsEnabled = $true
        $inputBox.Focus()
        # Show history if any
        $chatBox.Items.Clear()
        if ($script:responses[$char.Provider]) {
            foreach ($msg in $script:responses[$char.Provider]) {
                $chatBox.Items.Add($msg)
            }
        }
    })

    # Hover effect
    $border.Add_MouseEnter({ $border.Background = "#1c2333" })
    $border.Add_MouseLeave({ $border.Background = "#161b22" })

    return $border
}

function Invoke-AI {
    param($Provider, $Message)
    try {
        $body = @{message=$Message; provider=$Provider} | ConvertTo-Json -Compress
        $content = New-Object System.Net.Http.StringContent ($body, [System.Text.Encoding]::UTF8, "application/json")
        $resp = $client.PostAsync("$apiBase/api/chat", $content).Result
        $json = $resp.Content.ReadAsStringAsync().Result
        $data = $json | ConvertFrom-Json
        return if ($data.response) { $data.response } else { $data.error }
    } catch {
        return "Error: $($_.Exception.Message)"
    }
}

function Check-Health {
    try {
        $resp = $client.GetAsync("$apiBase/api/providers").Result
        if ($resp.IsSuccessStatusCode) {
            $json = $resp.Content.ReadAsStringAsync().Result
            $data = $json | ConvertFrom-Json
            foreach ($c in $script:chars) {
                $c.Loaded = [bool]($data.$($c.Provider))
            }
            $online = ($script:chars | Where-Object Loaded).Count
            $statusText.Text = "$online/5 characters ready"
            $trayStatus.Text = "🟢 Running - $online/5 online"

            # Refresh tiles
            $charPanel.Children.Clear()
            foreach ($c in $script:chars) {
                $charPanel.Children.Add((New-CharTile $c))
            }
            return $true
        }
    } catch {
        $statusText.Text = "⏳ Starting backend..."
        $trayStatus.Text = "🟡 Waiting for backend..."
    }
    return $false
}

# Send message
$sendBtn.Add_Click({
    $text = $inputBox.Text.Trim()
    if (-not $text -or -not $currentChar) { return }
    $inputBox.Text = ""

    $charObj = $script:chars | Where-Object { $_.Provider -eq $currentChar }
    $avatar = if ($charObj) { $charObj.Avatar } else { "🤖" }
    $name = if ($charObj) { $charObj.Name } else { $currentChar }

    $chatBox.Items.Add("🧑 You: $text")
    $chatBox.Items.Add("⏳ $name is thinking...")
    $chatBox.ScrollIntoView($chatBox.Items[$chatBox.Items.Count - 1])

    $resp = Invoke-AI -Provider $currentChar -Message $text

    # Remove thinking indicator
    $chatBox.Items.RemoveAt($chatBox.Items.Count - 1)

    $display = "$avatar $name`: $resp"
    $chatBox.Items.Add($display)
    $chatBox.ScrollIntoView($chatBox.Items[$chatBox.Items.Count - 1])

    # Store history
    if (-not $script:responses[$currentChar]) { $script:responses[$currentChar] = @() }
    $script:responses[$currentChar] += "🧑 You: $text"
    $script:responses[$currentChar] += $display
}

$inputBox.Add_KeyDown({
    if ($_.Key -eq "Return" -and -not $_.KeyboardDevice.Modifiers.HasFlag("Shift")) {
        $_.Handled = $true
        $sendBtn.RaiseEvent((New-Object Windows.RoutedEventArgs ([Windows.Controls.Primitives.ButtonBase]::ClickEvent)))
    }
})

# Initial health check and periodic timer
$win.Add_Loaded({
    Check-Health
    $timer = New-Object Windows.Threading.DispatcherTimer
    $timer.Interval = [TimeSpan]::FromSeconds(10)
    $timer.Add_Tick({ Check-Health })
    $timer.Start()
})

# System tray
$trayIcon = New-Object System.Windows.Forms.NotifyIcon
$trayIcon.Text = "AI Orchestrator Desktop"
$trayIcon.Icon = [System.Drawing.Icon]::ExtractAssociatedIcon((Get-Process -Id $pid).MainModule.FileName)
$trayIcon.Visible = $true
$trayIcon.Add_MouseDoubleClick({
    $win.Show()
    $win.WindowState = "Normal"
    $win.Activate()
})

$trayMenu = New-Object System.Windows.Forms.ContextMenuStrip
$showItem = New-Object System.Windows.Forms.ToolStripMenuItem ("Show")
$showItem.Add_Click({ $win.Show(); $win.Activate() })
$exitItem = New-Object System.Windows.Forms.ToolStripMenuItem ("Exit")
$exitItem.Add_Click({
    $trayIcon.Visible = $false
    $win.Close()
    [System.Windows.Application]::Current.Shutdown()
})
$trayMenu.Items.Add($showItem)
$trayMenu.Items.Add((New-Object System.Windows.Forms.ToolStripMenuItem ("-")))
$trayMenu.Items.Add($exitItem)
$trayIcon.ContextMenuStrip = $trayMenu

$win.Add_StateChanged({
    if ($win.WindowState -eq "Minimized") {
        $win.Hide()
    }
})

$win.Add_Closing({
    $trayIcon.Visible = $false
})

# Show
$win.ShowDialog() | Out-Null
