sub init()
    m.status = m.top.findNode("status")
    m.video = m.top.findNode("streamVideo")
    m.shade = m.top.findNode("shade")
    m.title = m.top.findNode("title")
    m.subtitle = m.top.findNode("subtitle")
    m.status = m.top.findNode("status")
    m.hint = m.top.findNode("hint")
    m.streamHint = m.top.findNode("streamHint")
    m.btnAddress = m.top.findNode("btnAddress")
    m.btnConnect = m.top.findNode("btnConnect")
    m.btnPair = m.top.findNode("btnPair")
    m.btnStart = m.top.findNode("btnStart")
    m.btnStop = m.top.findNode("btnStop")

    m.registry = CreateObject("roRegistrySection", "MoonlightRokuBridge")
    m.pcAddress = ""
    m.token = ""
    m.streaming = false
    m.dialogPurpose = ""
    if m.registry.Exists("pcAddress") then m.pcAddress = m.registry.Read("pcAddress")
    if m.registry.Exists("token") then m.token = m.registry.Read("token")
    updateButtons()
    m.btnAddress.observeField("buttonSelected", "onAddressSelected")
    m.btnConnect.observeField("buttonSelected", "onConnectSelected")
    m.btnPair.observeField("buttonSelected", "onPairSelected")
    m.btnStart.observeField("buttonSelected", "onStartSelected")
    m.btnStop.observeField("buttonSelected", "onStopSelected")
    m.top.setFocus(true)
    m.btnAddress.setFocus(true)
    if m.pcAddress <> "" then
        m.status.text = "PC configurado: " + m.pcAddress + chr(10) + "Teste a conexão antes de iniciar."
    end if
end sub

sub updateButtons()
    if m.pcAddress = "" then
        m.btnAddress.text = "1. Configurar IP do PC"
    else
        m.btnAddress.text = "1. PC: " + m.pcAddress
    end if
    if m.token = "" then
        m.btnPair.text = "3. Parear com PIN do PC"
    else
        m.btnPair.text = "3. Pareamento salvo (refazer PIN)"
    end if
end sub

function normalizeAddress(value as String) as String
    address = Trim(value)
    if address = "" then return ""
    if Left(LCase(address), 7) = "http://" or Left(LCase(address), 8) = "https://" then
        address = address
    else
        address = "http://" + address
    end if
    while Right(address, 1) = "/"
        address = Left(address, Len(address) - 1)
    end while
    return address
end function

function apiRequest(path as String, method as String, payload = invalid, authenticated = false as Boolean) as Dynamic
    if m.pcAddress = "" then return invalid
    xfer = CreateObject("roUrlTransfer")
    xfer.SetUrl(m.pcAddress + path)
    xfer.SetTimeout(8)
    xfer.AddHeader("Accept", "application/json")
    if authenticated and m.token <> "" then xfer.AddHeader("X-Bridge-Token", m.token)
    if method = "POST" then
        xfer.AddHeader("Content-Type", "application/json")
        if payload = invalid then payload = {}
        response = xfer.PostFromString(FormatJson(payload))
    else
        response = xfer.GetToString()
    end if
    if response = invalid or response = "" then return invalid
    return ParseJson(response)
end function

sub onAddressSelected()
    m.dialogPurpose = "address"
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "Endereço do PC"
    dialog.message = "Digite IP:PORTA. Exemplo: 192.168.1.20:8790"
    dialog.buttons = ["Salvar", "Cancelar"]
    dialog.text = m.pcAddress
    dialog.observeField("buttonSelected", "onKeyboardSelected")
    m.top.dialog = dialog
end sub

sub onPairSelected()
    if m.pcAddress = "" then
        m.status.text = "Configure o IP do PC primeiro."
        return
    end if
    m.dialogPurpose = "pin"
    dialog = CreateObject("roSGNode", "KeyboardDialog")
    dialog.title = "PIN exibido no PC"
    dialog.message = "Execute o bridge no PC e digite o PIN de 6 dígitos mostrado no terminal."
    dialog.buttons = ["Parear", "Cancelar"]
    dialog.text = ""
    dialog.observeField("buttonSelected", "onKeyboardSelected")
    m.top.dialog = dialog
end sub

sub onKeyboardSelected()
    dialog = m.top.dialog
    if dialog = invalid then return
    if dialog.buttonSelected <> 0 then
        m.top.dialog = invalid
        return
    end if
    entered = Trim(dialog.text)
    m.top.dialog = invalid
    if m.dialogPurpose = "address" then
        m.pcAddress = normalizeAddress(entered)
        if m.pcAddress = "" then
            m.status.text = "Endereço vazio. Informe IP:PORTA do PC."
            return
        end if
        m.registry.Write("pcAddress", m.pcAddress)
        m.registry.Flush()
        updateButtons()
        m.status.text = "Endereço salvo: " + m.pcAddress + chr(10) + "Agora teste a conexão."
    else if m.dialogPurpose = "pin" then
        if Len(entered) <> 6 then
            m.status.text = "PIN inválido. Digite os 6 dígitos exibidos no terminal do PC."
            return
        end if
        m.status.text = "Pareando com o PC..."
        result = apiRequest("/api/pair", "POST", { "pin": entered }, false)
        if result <> invalid and result.ok = true and result.token <> invalid then
            m.token = result.token
            m.registry.Write("token", m.token)
            m.registry.Flush()
            m.status.text = "Pareamento concluído. Agora inicie a transmissão."
            updateButtons()
        else
            m.status.text = "Falha no pareamento. Confira PIN e IP do PC."
        end if
    end if
end sub

sub onConnectSelected()
    if m.pcAddress = "" then
        m.status.text = "Configure o IP do PC primeiro."
        return
    end if
    m.status.text = "Testando o PC..."
    result = apiRequest("/api/status", "GET")
    if result = invalid or result.ok <> true then
        m.status.text = "Não consegui acessar o bridge em " + m.pcAddress + chr(10) + "Confira firewall, IP e se o servidor está rodando."
        return
    end if
    captureText = ""
    if result.capture <> invalid then captureText = result.capture
    m.status.text = "Bridge acessível. Captura: " + captureText + chr(10) + "Se ainda não pareou, use a opção 3."
end sub

sub onStartSelected()
    if m.pcAddress = "" then
        m.status.text = "Configure o IP do PC primeiro."
        return
    end if
    if m.token = "" then
        m.status.text = "Pareie com o PIN exibido no PC antes de iniciar."
        return
    end if
    m.status.text = "Iniciando captura e preparando HLS..."
    result = apiRequest("/api/start", "POST", {}, true)
    if result = invalid or result.ok <> true then
        err = "Bridge recusou iniciar a transmissão."
        if result <> invalid and result.error <> invalid then err = result.error
        m.status.text = err
        return
    end if
    content = CreateObject("roSGNode", "ContentNode")
    content.url = m.pcAddress + "/stream/live.m3u8"
    content.title = "PC Stream"
    content.streamformat = "hls"
    m.video.content = content
    m.video.visible = true
    m.video.control = "play"
    m.streaming = true
    setMenuVisible(false)
    m.streamHint.visible = true
    m.top.setFocus(true)
end sub

sub onStopSelected()
    stopStream()
end sub

sub setMenuVisible(isVisible as Boolean)
    m.shade.visible = isVisible
    m.title.visible = isVisible
    m.subtitle.visible = isVisible
    m.status.visible = isVisible
    m.hint.visible = isVisible
    m.btnAddress.visible = isVisible
    m.btnConnect.visible = isVisible
    m.btnPair.visible = isVisible
    m.btnStart.visible = isVisible
    m.btnStop.visible = isVisible
end sub

sub stopStream()
    if m.streaming then
        m.video.control = "stop"
        m.video.visible = false
        m.streaming = false
        result = apiRequest("/api/stop", "POST", {}, true)
    end if
    m.streamHint.visible = false
    setMenuVisible(true)
    m.status.text = "Transmissão parada."
    m.btnAddress.setFocus(true)
end sub

sub sendInput(keyName as String, action as String)
    if m.token = "" then return
    payload = { "key": keyName, "action": action }
    result = apiRequest("/api/input", "POST", payload, true)
end sub

function onKeyEvent(key as String, press as Boolean) as Boolean
    if not m.streaming then return false
    mapped = ""
    if key = "up" then mapped = "up"
    if key = "down" then mapped = "down"
    if key = "left" then mapped = "left"
    if key = "right" then mapped = "right"
    if key = "OK" then mapped = "ok"
    if key = "play" then mapped = "play"
    if key = "rewind" then mapped = "rewind"
    if key = "fastforward" then mapped = "tab"
    if key = "replay" then mapped = "backspace"
    if key = "back" and press then
        stopStream()
        return true
    end if
    if mapped <> "" then
        if mapped = "ok" or mapped = "play" or mapped = "rewind" or mapped = "tab" or mapped = "backspace" then
            if press then sendInput(mapped, "tap")
        else
            if press then
                sendInput(mapped, "down")
            else
                sendInput(mapped, "up")
            end if
        end if
        return true
    end if
    return false
end function
