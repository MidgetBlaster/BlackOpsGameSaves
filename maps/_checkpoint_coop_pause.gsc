// Co-op break control for new devcommands sessions.
// Based on the supplied _custom.gsc. Keep the server and network running;
// pausing the BlackOps process itself disconnects remote players.

init()
{
	SetDvar( "checkpoint_coop_pause", "0" );
	level.checkpoint_coop_paused = false;
	level thread watch_pause_request();
}

watch_pause_request()
{
	level endon( "end_game" );
	for( ;; )
	{
		players = get_players();
		requested = GetDvarInt( "checkpoint_coop_pause" ) != 0;
		if( players.size < 2 )
		{
			requested = false;
			if( GetDvarInt( "checkpoint_coop_pause" ) != 0 )
				SetDvar( "checkpoint_coop_pause", "0" );
		}

		if( requested && !level.checkpoint_coop_paused )
			begin_pause();
		else if( !requested && level.checkpoint_coop_paused )
			end_pause();

		if( level.checkpoint_coop_paused )
		{
			players = get_players();
			for( i = 0; i < players.size; i++ )
				protect_player( players[i] );
		}
		wait 0.1;
	}
}

begin_pause()
{
	level.checkpoint_old_ai = GetDvar( "g_ai" );
	level.checkpoint_old_spawn = GetDvar( "ai_disableSpawn" );
	level.checkpoint_old_spawn_flag = flag( "spawn_zombies" );
	flag_clear( "spawn_zombies" );
	SetDvar( "g_ai", "0" );
	SetDvar( "ai_disableSpawn", "1" );
	level.checkpoint_coop_paused = true;

	level.checkpoint_pause_hud = NewHudElem();
	level.checkpoint_pause_hud.horzAlign = "center";
	level.checkpoint_pause_hud.vertAlign = "middle";
	level.checkpoint_pause_hud.fontScale = 2;
	level.checkpoint_pause_hud.foreground = true;
	level.checkpoint_pause_hud SetText( "CO-OP PAUSED" );

	players = get_players();
	for( i = 0; i < players.size; i++ )
		protect_player( players[i] );
}

protect_player( player )
{
	if( !isDefined( player.checkpoint_pause_protected ) || !player.checkpoint_pause_protected )
	{
		if( isDefined( player.ignoreme ) )
			player.checkpoint_pause_old_ignoreme = player.ignoreme;
		player.checkpoint_pause_old_invulnerable = IsGodMode( player );
		player.checkpoint_pause_protected = true;
		player EnableInvulnerability();
	}
	player freezecontrols( true );
	player.ignoreme = 1;
}

end_pause()
{
	level.checkpoint_coop_paused = false;
	players = get_players();
	for( i = 0; i < players.size; i++ )
	{
		player = players[i];
		if( isDefined( player.checkpoint_pause_protected ) && player.checkpoint_pause_protected )
		{
			player freezecontrols( false );
			if( !player.checkpoint_pause_old_invulnerable )
				player DisableInvulnerability();
			if( isDefined( player.checkpoint_pause_old_ignoreme ) )
				player.ignoreme = player.checkpoint_pause_old_ignoreme;
			else
				player.ignoreme = 0;
			player.checkpoint_pause_protected = false;
		}
	}
	if( isDefined( level.checkpoint_pause_hud ) )
		level.checkpoint_pause_hud Destroy();
	SetDvar( "g_ai", level.checkpoint_old_ai );
	SetDvar( "ai_disableSpawn", level.checkpoint_old_spawn );
	if( level.checkpoint_old_spawn_flag )
		flag_set( "spawn_zombies" );
}
